"""
状态驱动调度器（七岗多智能体版）

轮询「分析任务」表中的待处理记录，对每条任务调用完整的七岗 DAG 分析流水线：
  待分析 → [Wave1: 5个并行Agent] → [Wave2: 财务顾问] → [Wave3: CEO助理] → 已完成

崩溃恢复：ANALYZING 状态为上次崩溃遗留，重置回待分析重新处理。
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

logger = logging.getLogger(__name__)

# 单轮最多处理任务数（每条任务触发 7 次 LLM 调用）
_MAX_PER_CYCLE = 3


async def run_one_cycle(app_token: str, table_ids: dict) -> int:
    """
    执行一轮完整的多智能体分析处理：
      0. 恢复崩溃遗留的 ANALYZING 记录 → 重置为待分析
      1. 领取「待分析」任务，逐条执行七岗 DAG 流水线
      2. 将各岗分析输出写入「岗位分析」表
      3. 将 CEO 助理综合报告写入「综合报告」表
      4. 更新「数字员工效能」表

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
                app_token, task_tid, rid, {"状态": Status.ANALYZING}
            )

            # 清理此任务可能遗留的历史输出（重试或崩溃恢复场景）
            await cleanup_prior_task_outputs(app_token, task_title, output_tid, report_tid)

            # 执行七岗 DAG 分析流水线（Wave1→Wave2→Wave3）
            all_results, ceo_result = await run_task_pipeline(fields)

            # 写入各岗分析输出（可选表，部分失败不阻断主流程）
            if output_tid:
                await write_agent_outputs(app_token, output_tid, task_title, all_results)

            # 写入 CEO 综合报告（核心交付物；失败直接抛出使整条任务回到待分析）
            await write_ceo_report(
                app_token,
                report_tid,
                task_title,
                ceo_result,
                participant_count=len(all_results) + 1,  # +1 for ceo_assistant
            )

            # 更新员工效能（含 CEO 助理本身）
            if performance_tid:
                await update_performance(
                    app_token, performance_tid, all_results + [ceo_result]
                )

            # 标记为已完成
            await bitable_ops.update_record(
                app_token,
                task_tid,
                rid,
                {
                    "状态": Status.COMPLETED,
                    "完成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
                },
            )
            processed += 1
            logger.info("Task [%s] completed by 7-agent pipeline", task_title)

        except Exception as exc:
            logger.error("Pipeline failed for task=%s record=%s: %s", task_title, rid, exc)
            try:
                await bitable_ops.update_record(
                    app_token, task_tid, rid, {"状态": Status.PENDING}
                )
            except Exception as reset_exc:
                logger.error(
                    "Failed to reset task=%s back to PENDING: %s — task may remain stuck in ANALYZING",
                    task_title, reset_exc,
                )

    return processed
