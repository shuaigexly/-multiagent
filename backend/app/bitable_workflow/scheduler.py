"""
状态驱动调度器（七岗多智能体版）

轮询「分析任务」表中的待处理记录，对每条任务调用完整的七岗 DAG 分析流水线：
  待分析 → [Wave1: 5个并行Agent] → [Wave2: 财务顾问] → [Wave3: CEO助理] → 已完成

崩溃恢复：ANALYZING 状态为上次崩溃遗留，重置回待分析重新处理。
反馈闭环：任务完成后，CEO 助理行动项自动写回「分析任务」表形成新的待分析任务。
飞书通知：任务完成后向配置的飞书群推送摘要卡片消息。
"""
import asyncio
import logging
import os
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.schema import Status
from app.bitable_workflow.workflow_agents import (
    cleanup_prior_task_output_ids,
    collect_prior_task_output_ids,
    run_task_pipeline,
    update_performance,
    write_agent_outputs,
    write_ceo_report,
)
from app.agents.base_agent import AgentResult
from app.core.observability import set_task_context
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)

# 单轮最多处理任务数（每条任务触发 7 次 LLM 调用）
_MAX_PER_CYCLE = 3
_LOCAL_CYCLE_LOCK: asyncio.Lock | None = None
_LOCK_TTL_SECONDS = int(os.getenv("WORKFLOW_CYCLE_LOCK_TTL_SECONDS", "900"))
_RECOVER_STALE_MINUTES = int(os.getenv("WORKFLOW_RECOVER_STALE_MINUTES", "30"))
_ALLOW_LOCAL_WORKFLOW_LOCK = os.getenv("WORKFLOW_ALLOW_LOCAL_LOCK", "").lower() in {
    "1",
    "true",
    "yes",
}


def _owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex}"


def _cycle_lock_key(app_token: str, task_tid: str) -> str:
    return f"workflow:cycle-lock:{app_token}:{task_tid}"


async def _acquire_cycle_lock(app_token: str, task_tid: str) -> tuple[object | None, str | None]:
    global _LOCAL_CYCLE_LOCK
    if _LOCAL_CYCLE_LOCK is None:
        _LOCAL_CYCLE_LOCK = asyncio.Lock()
    await _LOCAL_CYCLE_LOCK.acquire()
    owner = _owner_id()
    try:
        import redis.asyncio as aioredis
        from app.core.settings import settings

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        ok = await client.set(
            _cycle_lock_key(app_token, task_tid),
            owner,
            nx=True,
            ex=_LOCK_TTL_SECONDS,
        )
        if not ok:
            _LOCAL_CYCLE_LOCK.release()
            await client.aclose()
            return None, None
        return client, owner
    except Exception as exc:
        env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
        if env in {"prod", "production"} and not _ALLOW_LOCAL_WORKFLOW_LOCK:
            _LOCAL_CYCLE_LOCK.release()
            raise RuntimeError("Redis workflow lock is required in production") from exc
        logger.warning("Redis workflow lock unavailable; using in-process lock only: %s", exc)
        return None, owner


async def _release_cycle_lock(lock_client: object | None, owner: str | None, app_token: str, task_tid: str) -> None:
    try:
        if lock_client is not None and owner:
            key = _cycle_lock_key(app_token, task_tid)
            current = await lock_client.get(key)
            if current == owner:
                await lock_client.delete(key)
            await lock_client.aclose()
    finally:
        if _LOCAL_CYCLE_LOCK is not None and _LOCAL_CYCLE_LOCK.locked():
            _LOCAL_CYCLE_LOCK.release()


async def _renew_cycle_lock(lock_client: object, owner: str, app_token: str, task_tid: str) -> None:
    """Keep the distributed workflow lock alive while a long analysis cycle runs."""
    key = _cycle_lock_key(app_token, task_tid)
    interval = max(5, min(60, _LOCK_TTL_SECONDS // 3))
    while True:
        await asyncio.sleep(interval)
        current = await lock_client.get(key)
        if current != owner:
            raise RuntimeError("Lost Redis workflow lock ownership")
        await lock_client.expire(key, _LOCK_TTL_SECONDS)


def _parse_feishu_time(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _build_dep_index(app_token: str, task_tid: str) -> dict[str, str]:
    """构建 任务编号 → 状态 索引，供依赖检查使用。

    任务编号 字段类型为 AutoNumber，飞书会以序列号字符串返回（如 '1', '2', '3'）。
    若该字段缺失或返回结构异常，统一以空字符串兜底，让依赖检查降级为通过。
    """
    index: dict[str, str] = {}
    try:
        rows = await bitable_ops.list_records(app_token, task_tid, max_records=200)
    except Exception as exc:
        logger.debug("dep index list_records failed (skip dep check): %s", exc)
        return index
    for r in rows:
        f = r.get("fields") or {}
        num = f.get("任务编号")
        # AutoNumber 在 SDK 中可能返回 dict {"value": [{"text": "1"}]} 或 直接字符串
        num_str = ""
        if isinstance(num, str):
            num_str = num.strip()
        elif isinstance(num, dict):
            value = num.get("value")
            if isinstance(value, list) and value:
                first = value[0]
                num_str = (first.get("text") if isinstance(first, dict) else str(first)) or ""
        elif isinstance(num, (int, float)):
            num_str = str(int(num))
        if num_str:
            index[num_str.lstrip("T0").lstrip("0") or num_str] = f.get("状态") or ""
    return index


def _unmet_dependencies(dep_field: object, dep_index: dict[str, str]) -> list[str]:
    """解析依赖任务编号字段，返回未完成的依赖列表。

    格式宽松：
      - "1, 3"  / "T0001, T0003" / "1；3" / "1\n3" 都识别
      - 缺省 / 空白 / 解析失败 → 视为无依赖
    """
    if not dep_field:
        return []
    raw = str(dep_field) if not isinstance(dep_field, str) else dep_field
    parts = [p.strip().lstrip("T0").lstrip("0") for p in re.split(r"[,，;；\n\s]+", raw) if p.strip()]
    unmet: list[str] = []
    for num in parts:
        if not num:
            continue
        status = dep_index.get(num)
        if status is None:
            # 引用了不存在的任务编号 — 容错：视为未完成（用户应改正字段）
            unmet.append(f"T{num}(未知)")
        elif status != Status.COMPLETED:
            unmet.append(f"T{num}({status or '空状态'})")
    return unmet


def _is_stale_analyzing(fields: dict) -> bool:
    updated_at = _parse_feishu_time(fields.get("最近更新"))
    if updated_at is None:
        return False
    return datetime.now(timezone.utc) - updated_at > timedelta(minutes=_RECOVER_STALE_MINUTES)


async def _claim_pending_record(
    app_token: str,
    task_tid: str,
    record_id: str,
    owner: str,
) -> bool:
    """Best-effort claim verification for Bitable rows that lack a true CAS API."""
    claim_stage = f"🔒 已领取：{owner}"
    await bitable_ops.update_record(
        app_token,
        task_tid,
        record_id,
        {"状态": Status.ANALYZING, "当前阶段": claim_stage, "进度": 0.01},
    )
    claimed = await bitable_ops.get_record(app_token, task_tid, record_id)
    fields = claimed.get("fields") or {}
    return fields.get("状态") == Status.ANALYZING and fields.get("当前阶段") == claim_stage


async def _send_completion_message(task_title: str, ceo_result: AgentResult) -> None:
    """任务完成后向飞书群推送摘要卡片。未配置 chat_id 时静默跳过。"""
    try:
        from app.feishu.im import send_card_message
        summary = truncate_with_marker(ceo_result.raw_output or "七岗多智能体分析已完成", 2000)
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
                    "任务标题": f"[跟进] {truncate_with_marker(item, 50, '...[截断]')}",
                    "分析维度": "综合分析",
                    "优先级": "P2 中",
                    "状态": Status.PENDING,
                    "进度": 0,
                    "背景说明": f"由任务「{task_title}」的CEO助理决策建议自动生成",
                },
            )
            logger.info(
                "Follow-up task created from [%s]: %s",
                task_title,
                truncate_with_marker(item, 50, "...[截断]"),
            )
        except Exception as exc:
            logger.warning("Failed to create follow-up task from [%s]: %s", task_title, exc)


async def run_one_cycle(app_token: str, table_ids: dict) -> int:
    task_tid = table_ids["task"]
    lock_client, lock_owner = await _acquire_cycle_lock(app_token, task_tid)
    if lock_owner is None:
        logger.info("Workflow cycle skipped because another instance holds the lock")
        return 0
    renew_task: asyncio.Task | None = None
    if lock_client is not None and lock_owner:
        renew_task = asyncio.create_task(
            _renew_cycle_lock(lock_client, lock_owner, app_token, task_tid)
        )
    try:
        return await _run_one_cycle_locked(app_token, table_ids)
    finally:
        if renew_task is not None:
            renew_task.cancel()
            try:
                await renew_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("Workflow lock renewal stopped with error: %s", exc)
        await _release_cycle_lock(lock_client, lock_owner, app_token, task_tid)


async def _run_one_cycle_locked(app_token: str, table_ids: dict) -> int:
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
        fields = record.get("fields", {})
        if not _is_stale_analyzing(fields):
            logger.info("Skipping active ANALYZING record=%s; not stale enough for recovery", rid)
            continue
        try:
            await bitable_ops.update_record(
                app_token, task_tid, rid, {"状态": Status.PENDING}
            )
            logger.warning("Recovered stuck ANALYZING record=%s → 待分析", rid)
        except Exception as exc:
            logger.error("Failed to recover ANALYZING record=%s: %s", rid, exc)

    # Phase 1: 领取待分析任务，按优先级排序后逐条执行
    # 拉取多于 _MAX_PER_CYCLE 的候选，本地按优先级排序后只取前 _MAX_PER_CYCLE
    pending_pool_size = _MAX_PER_CYCLE * 4
    pending = await bitable_ops.list_records(
        app_token,
        task_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.PENDING}"',
        page_size=min(50, pending_pool_size),
        max_records=pending_pool_size,
    )

    # 优先级排序：P0 紧急 < P1 高 < P2 中 < P3 低 < 未填
    _PRIO_ORDER = {"P0 紧急": 0, "P1 高": 1, "P2 中": 2, "P3 低": 3}
    pending.sort(
        key=lambda r: _PRIO_ORDER.get((r.get("fields") or {}).get("优先级", ""), 99)
    )
    pending = pending[:_MAX_PER_CYCLE]
    if pending:
        prio_summary = [
            (r.get("fields") or {}).get("优先级", "?") for r in pending
        ]
        logger.info("Phase 1 picked %d tasks by priority: %s", len(pending), prio_summary)

    # 任务依赖图：构建 任务编号 → status 的全表索引（便于检查依赖）
    dep_index = await _build_dep_index(app_token, task_tid)

    for record in pending:
        rid = record.get("record_id", "?")
        fields = record.get("fields", {})
        task_title = fields.get("任务标题", f"任务_{rid[:8]}")

        # 绑定 task_id 上下文 — 此后所有 logger.* 调用自动带上 task_id，便于聚合查询
        set_task_context(task_id=rid)

        # 任务依赖检查：「依赖任务编号」中的所有任务必须 已完成 才能启动
        unmet_deps = _unmet_dependencies(fields.get("依赖任务编号"), dep_index)
        if unmet_deps:
            stage_msg = f"⏸ 等待依赖任务：{', '.join(unmet_deps[:3])}"
            try:
                await bitable_ops.update_record(
                    app_token, task_tid, rid, {"当前阶段": stage_msg}
                )
            except Exception as upd_exc:
                logger.debug("dep wait stage update failed: %s", upd_exc)
            logger.info("Task [%s] blocked by deps: %s", task_title, unmet_deps)
            continue

        try:
            # 标记为「分析中」并回读校验 owner，降低多实例重复领取概率。
            claim_owner = _owner_id()
            if not await _claim_pending_record(app_token, task_tid, rid, claim_owner):
                logger.warning("Workflow claim lost for record=%s owner=%s", rid, claim_owner)
                continue

            await bitable_ops.update_record(
                app_token, task_tid, rid,
                {"当前阶段": "▶ Wave1 启动：五岗并行分析中…", "进度": 0.1}
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

            # 先记录历史输出 ID；新输出和报告全部写入成功后再清理旧记录，避免重试失败丢失上次好结果。
            prior_output_ids = await collect_prior_task_output_ids(
                app_token, task_title, output_tid, report_tid
            )

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

            try:
                await cleanup_prior_task_output_ids(
                    app_token, output_tid, report_tid, prior_output_ids
                )
            except Exception as cleanup_exc:
                logger.warning(
                    "Prior output cleanup failed after successful replacement for task=%s: %s",
                    task_title,
                    cleanup_exc,
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
                    {"状态": Status.PENDING, "当前阶段": f"❌ 执行失败，将重试：{truncate_with_marker(exc, 100, '...[截断]')}"}
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
                    rid, "task.error", {"reason": truncate_with_marker(exc, 200, "...[截断]")},
                )
            except Exception:
                pass

    return processed
