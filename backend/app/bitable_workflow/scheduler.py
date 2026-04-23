"""
状态驱动调度器

轮询多维表格中的待处理记录，按状态分派给对应的 Agent。
流转链路：待选题 → [EditorAgent] → 待审核 → [ReviewerAgent] → 已发布/审核拒绝

崩溃恢复：WRITING 状态为上次崩溃遗留，重置回待选题重新处理。
"""
import logging

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.schema import Status
from app.bitable_workflow.workflow_agents import EditorAgent, ReviewerAgent

logger = logging.getLogger(__name__)

_editor = EditorAgent()
_reviewer = ReviewerAgent()

# 单轮最多处理条数，防止单次 LLM 调用堆积过多
_MAX_PER_PHASE = 5


async def run_one_cycle(app_token: str, table_ids: dict) -> int:
    """
    执行一轮完整的状态处理：
    0. 恢复崩溃遗留的 WRITING 记录 → 重置为待选题
    1. 编辑处理「待选题」→ 写草稿 → 更新为「待审核」
    2. 审核员处理「待审核」→ 评审 → 更新为「已发布」或「审核拒绝」

    返回本轮处理的记录总数。
    """
    content_tid = table_ids["content"]
    performance_tid = table_ids.get("performance")
    processed = 0

    # Phase 0: 恢复 WRITING 状态的悬挂记录
    stuck_writing = await bitable_ops.list_records(
        app_token,
        content_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.WRITING}"',
    )
    for record in stuck_writing:
        rid = record.get("record_id", "?")
        try:
            await bitable_ops.update_record(
                app_token, content_tid, rid, {"状态": Status.PENDING_TOPIC}
            )
            logger.warning("Recovered stuck WRITING record=%s → 待选题", rid)
        except Exception as exc:
            logger.error("Failed to recover WRITING record=%s: %s", rid, exc)

    # Phase 1: 编辑领取「待选题」任务
    pending_topics = await bitable_ops.list_records(
        app_token,
        content_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.PENDING_TOPIC}"',
        page_size=_MAX_PER_PHASE,
        max_records=_MAX_PER_PHASE,
    )
    for record in pending_topics:
        rid = record.get("record_id", "?")
        try:
            await bitable_ops.update_record(
                app_token, content_tid, rid, {"状态": Status.WRITING}
            )
            await _editor.process(app_token, content_tid, record, performance_table_id=performance_tid)
            processed += 1
        except Exception as exc:
            logger.error("Editor failed record=%s: %s", rid, exc)
            try:
                await bitable_ops.update_record(
                    app_token, content_tid, rid, {"状态": Status.PENDING_TOPIC}
                )
            except Exception:
                pass

    # Phase 2: 审核员领取「待审核」任务
    pending_reviews = await bitable_ops.list_records(
        app_token,
        content_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.PENDING_REVIEW}"',
        page_size=_MAX_PER_PHASE,
        max_records=_MAX_PER_PHASE,
    )
    for record in pending_reviews:
        rid = record.get("record_id", "?")
        try:
            await _reviewer.process(app_token, content_tid, record, performance_table_id=performance_tid)
            processed += 1
        except Exception as exc:
            logger.error("Reviewer failed record=%s: %s", rid, exc)

    return processed
