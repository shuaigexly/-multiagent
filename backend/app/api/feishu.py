"""飞书发布 API"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.event_emitter import EventEmitter
from app.feishu.publisher import publish_results
from app.models.database import Task, TaskResult, get_db
from app.models.schemas import PublishRequest, PublishResponse
from app.agents.base_agent import AgentResult, ResultSection

router = APIRouter(prefix="/api/v1/tasks", tags=["feishu"])
logger = logging.getLogger(__name__)


@router.post("/{task_id}/publish", response_model=PublishResponse)
async def publish_task(
    task_id: str,
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != "done":
        raise HTTPException(400, "任务尚未完成")

    results_q = await db.execute(
        select(TaskResult).where(TaskResult.task_id == task_id)
    )
    task_results = results_q.scalars().all()

    agent_results = [
        AgentResult(
            agent_id=r.agent_id,
            agent_name=r.agent_name,
            sections=[ResultSection(**s) for s in (r.sections or [])],
            action_items=r.action_items or [],
            raw_output=r.raw_output or "",
        )
        for r in task_results
    ]

    emitter = EventEmitter(task_id=task_id, db=db)
    published = await publish_results(
        task_id=task_id,
        task_description=task.input_text or "",
        task_type_label=task.task_type_label or "",
        agent_results=agent_results,
        asset_types=body.asset_types,
        db=db,
        emitter=emitter,
        doc_title=body.doc_title,
        chat_id=body.chat_id,
    )

    return PublishResponse(published=published)


@router.get("/agents")
async def list_agents():
    """返回所有可用 Agent 模块信息"""
    from app.agents.registry import AGENT_INFO
    return {"agents": AGENT_INFO}
