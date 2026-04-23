"""
状态驱动调度器

轮询多维表格中的待处理记录，按状态分派给对应的 Agent。
流转链路：待选题 → [EditorAgent] → 待审核 → [ReviewerAgent] → 已发布/审核拒绝
"""
import logging

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.schema import Status
from app.bitable_workflow.workflow_agents import EditorAgent, ReviewerAgent

logger = logging.getLogger(__name__)

_editor = EditorAgent()
_reviewer = ReviewerAgent()


async def run_one_cycle(app_token: str, table_ids: dict) -> int:
    """
    执行一轮完整的状态处理：
    1. 编辑处理「待选题」→ 写草稿 → 更新为「待审核」
    2. 审核员处理「待审核」→ 评审 → 更新为「已发布」或「审核拒绝」

    返回本轮处理的记录总数。
    """
    content_tid = table_ids["content"]
    processed = 0

    # Phase 1: 编辑领取「待选题」任务
    pending_topics = await bitable_ops.list_records(
        app_token,
        content_tid,
        filter_expr=f'CurrentValue.[状态]="{Status.PENDING_TOPIC}"',
    )
    for record in pending_topics:
        rid = record.get("record_id", "?")
        try:
            await bitable_ops.update_record(
                app_token, content_tid, rid, {"状态": Status.WRITING}
            )
            await _editor.process(app_token, content_tid, record)
            processed += 1
        except Exception as exc:
            logger.error("Editor failed record=%s: %s", rid, exc)
            # 还原状态，避免卡死
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
    )
    for record in pending_reviews:
        rid = record.get("record_id", "?")
        try:
            await _reviewer.process(app_token, content_tid, record)
            processed += 1
        except Exception as exc:
            logger.error("Reviewer failed record=%s: %s", rid, exc)

    return processed
