"""
状态驱动调度器（七岗多智能体版）

轮询「分析任务」表中的待处理记录，对每条任务调用完整的七岗 DAG 分析流水线：
  待分析 → [Wave1: 5个并行Agent] → [Wave2: 财务顾问] → [Wave3: CEO助理] → 已完成

崩溃恢复：ANALYZING 状态为上次崩溃遗留，重置回待分析重新处理。
反馈闭环：任务完成后，CEO 助理行动项自动写回「分析任务」表形成新的待分析任务。
飞书通知：任务完成后向配置的飞书群推送摘要卡片消息。
"""
import logging
from datetime import datetime

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.schema import Status
from app.bitable_workflow.workflow_agents import (
    cleanup_prior_task_outputs,
    run_task_pipeline,
    update_performance,
    write_agent_outputs,
    write_ceo_report,
)
from app.agents.base_agent import AgentResult

logger = logging.getLogger(__name__)

# 单轮最多处理任务数（每条任务触发 7 次 LLM 调用）
_MAX_PER_CYCLE = 3


async def _send_completion_message(task_title: str, ceo_result: AgentResult) -> None:
    """任务完成后向飞书群推送摘要卡片。未配置 chat_id 时静默跳过。"""
    try:
        from app.feishu.im import send_card_message
        summary = (ceo_result.raw_output or "七岗多智能体分析已完成")[:2000]
        await send_card_message(title=f"分析完成：{task_title}", content=summary)
        logger.info("Feishu notification sent for task [%s]", task_title)
    except ValueError:
        # feishu_chat_id 未配置，静默跳过
        logger.debug("feishu_chat_id not configured, skipping notification for task [%s]", task_title)
    except Exception as exc:
        logger.warning("Feishu notification failed for task [%s]: %s", task_title, exc)


async def _create_followup_tasks(
    app_token: str,
    task_tid: str,
    task_title: str,
    ceo_result: AgentResult,
) -> None:
    """将 CEO 助理行动项转化为新的「待分析」任务，实现业务闭环（再流转）。

    同时尝试通过飞书任务 API 创建待办事项，方便在飞书中直接跟进。
    只取前 3 条非空行动项；跟进任务本身不再生成二级跟进，避免无限循环。
    """
    if task_title.startswith("[跟进]"):
        return

    action_items = [item.strip() for item in (ceo_result.action_items or []) if item.strip()][:3]
    if not action_items:
        logger.debug("No action items for follow-up from task [%s]", task_title)
        return

    # 1. 写入飞书任务 API（待办事项），便于在飞书客户端直接追踪
    try:
        from app.feishu.task import batch_create_tasks
        await batch_create_tasks(action_items)
        logger.info("Created %d Feishu tasks for [%s]", len(action_items), task_title)
    except Exception as exc:
        logger.warning("Feishu task API failed for [%s]: %s", task_title, exc)

    # 2. 在「分析任务」表中生成后续待分析记录（再流转闭环）
    for item in action_items:
        try:
            await bitable_ops.create_record(
                app_token,
                task_tid,
                {
                    "任务标题": f"[跟进] {item[:50]}",
                    "分析维度": "综合分析",
                    "优先级": "P2 中",
                    "状态": Status.PENDING,
                    "进度": 0,
                    "背景说明": f"由任务「{task_title}」的CEO助理决策建议自动生成",
                },
            )
            logger.info("Follow-up task created from [%s]: %s", task_title, item[:50])
        except Exception as exc:
            logger.warning("Failed to create follow-up task from [%s]: %s", task_title, exc)


async def run_one_cycle(app_token: str, table_ids: dict) -> int:
    """
    执行一轮完整的多智能体分析处理：
      0. 恢复崩溃遗留的 ANALYZING 记录 → 重置为待分析
      1. 领取「待分析」任务，逐条执行七岗 DAG 流水线
      2. 将各岗分析输出写入「岗位分析」表（含关联字段）
      3. 将 CEO 助理综合报告写入「综合报告」表（含关联字段）
      4. 更新「数字员工效能」表
      5. 发送飞书消息通知
      6. CEO 行动项生成新的「待分析」任务（再流转闭环）

    返回本轮成功完成的任务数。
    """
    task_tid = table_ids["task"]
    output_tid = table_ids.get("output")
    report_tid = table_ids["report"]
    performance_tid = table_ids.get("performance")
    processed = 0

    # Phase 0: 恢复 ANALYZING 悬挂记录（上次崩溃遗留）
    stuck = await bitable_ops.list_records(
        app_token,
        task_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.ANALYZING}"',
    )
    for record in stuck:
        rid = record.get("record_id")
        if not rid:
            logger.warning("Stuck record missing record_id, skipping: %s", record)
            continue
        try:
            await bitable_ops.update_record(
                app_token, task_tid, rid, {"状态": Status.PENDING}
            )
            logger.warning("Recovered stuck ANALYZING record=%s → 待分析", rid)
        except Exception as exc:
            logger.error("Failed to recover ANALYZING record=%s: %s", rid, exc)

    # Phase 1: 领取待分析任务，逐条执行七岗流水线
    pending = await bitable_ops.list_records(
        app_token,
        task_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.PENDING}"',
        page_size=_MAX_PER_CYCLE,
        max_records=_MAX_PER_CYCLE,
    )

    for record in pending:
        rid = record.get("record_id", "?")
        fields = record.get("fields", {})
        task_title = fields.get("任务标题", f"任务_{rid[:8]}")

        try:
            # 标记为「分析中」防止并发重复领取
            await bitable_ops.update_record(
                app_token, task_tid, rid,
                {"状态": Status.ANALYZING, "当前阶段": "▶ Wave1 启动：五岗并行分析中…", "进度": 0.1}
            )

            from app.bitable_workflow import progress_broker
            await progress_broker.publish(
                rid, "task.started",
                {"title": task_title, "stage": "Wave1 启动：五岗并行分析中…", "progress": 0.1},
            )

            # 每个 Wave 完成后更新「当前阶段」+「进度」字段，让用户在多维表格实时看到进展
            _wave_progress = iter([0.45, 0.75, 0.95])

            async def _on_wave(stage: str) -> None:
                progress = next(_wave_progress, 0.95)
                try:
                    await bitable_ops.update_record(
                        app_token, task_tid, rid, {"当前阶段": stage, "进度": progress}
                    )
                except Exception as stage_exc:
                    logger.debug("当前阶段 update skipped: %s", stage_exc)
                await progress_broker.publish(
                    rid, "wave.completed", {"stage": stage, "progress": progress},
                )

            # 执行七岗 DAG 分析流水线（Wave1→Wave2→Wave3）
            # 传入 rid 作为 task_id，启用 Redis 缓存：崩溃重试会跳过已完成的 agent
            all_results, ceo_result = await run_task_pipeline(
                fields, progress_callback=_on_wave, task_id=rid
            )

            # 清理此任务可能遗留的历史输出（重试或崩溃恢复场景）
            await cleanup_prior_task_outputs(app_token, task_title, output_tid, report_tid)

            # 写入各岗分析输出（含关联字段；写入不完整会使整条任务重试）
            if output_tid:
                output_written = await write_agent_outputs(
                    app_token, output_tid, task_title, all_results, task_record_id=rid
                )
                if output_written != len(all_results):
                    raise RuntimeError(f"岗位分析写入不完整: {output_written}/{len(all_results)}")

            # 写入 CEO 综合报告（含关联字段；核心交付物，失败直接抛出）
            await write_ceo_report(
                app_token,
                report_tid,
                task_title,
                ceo_result,
                participant_count=len(all_results) + 1,  # +1 for ceo_assistant
                task_record_id=rid,
            )

            # 更新员工效能（含 CEO 助理本身）
            if performance_tid:
                await update_performance(
                    app_token, performance_tid, all_results + [ceo_result]
                )

            # 标记为已完成，进度置为 100%
            await bitable_ops.update_record(
                app_token,
                task_tid,
                rid,
                {
                    "状态": Status.COMPLETED,
                    "当前阶段": "✅ 七岗分析全部完成",
                    "进度": 1.0,
                    "完成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                },
            )
            processed += 1
            logger.info("Task [%s] completed by 7-agent pipeline", task_title)

            # 任务成功完成 → 清除 Redis 缓存 + 广播 SSE task.done
            try:
                from app.bitable_workflow.agent_cache import invalidate_task_cache
                await invalidate_task_cache(rid)
            except Exception as cache_exc:
                logger.debug("cache invalidate failed: %s", cache_exc)
            await progress_broker.publish(
                rid, "task.done",
                {"title": task_title, "progress": 1.0, "participant_count": len(all_results) + 1},
            )

            # 飞书消息通知（非阻塞，失败不影响任务状态）
            await _send_completion_message(task_title, ceo_result)

            # 反馈再流转：CEO 行动项 → 新的待分析任务
            await _create_followup_tasks(app_token, task_tid, task_title, ceo_result)

        except Exception as exc:
            logger.error("Pipeline failed for task=%s record=%s: %s", task_title, rid, exc)
            try:
                await bitable_ops.update_record(
                    app_token, task_tid, rid,
                    {"状态": Status.PENDING, "当前阶段": f"❌ 执行失败，将重试：{str(exc)[:100]}"}
                )
            except Exception as reset_exc:
                logger.error(
                    "Failed to reset task=%s back to PENDING: %s — task may remain stuck in ANALYZING",
                    task_title, reset_exc,
                )
            # 不清除缓存 — 下次重试可复用已完成的 agent 结果
            try:
                from app.bitable_workflow import progress_broker
                await progress_broker.publish(
                    rid, "task.error", {"reason": str(exc)[:200]},
                )
            except Exception:
                pass

    return processed
