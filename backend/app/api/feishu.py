"""飞书发布 API"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.event_emitter import EventEmitter
from app.feishu.publisher import publish_results
from app.models.database import Task, TaskResult, get_db
from app.models.schemas import PublishRequest, PublishResponse
from app.agents.base_agent import AgentResult, ResultSection

router = APIRouter(tags=["feishu"])
logger = logging.getLogger(__name__)


class CreateTaskRequest(BaseModel):
    summary: str
    source_task_id: str | None = None


@router.post(
    "/api/v1/tasks/{task_id}/publish",
    response_model=PublishResponse,
    dependencies=[Depends(require_api_key)],
)
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
    if "message" in body.asset_types or "card" in body.asset_types:
        if not body.chat_id:
            from app.feishu.user_token import get_user_open_id

            if not get_user_open_id():
                raise HTTPException(400, "发送消息/卡片需要提供目标群 ID（chat_id），或先在设置页完成飞书 OAuth 授权")

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
            chart_data=r.chart_data or [],
        )
        for r in task_results
    ]

    emitter = EventEmitter(task_id=task_id, db=db)
    publish_result = await publish_results(
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

    return PublishResponse(**publish_result)


@router.post("/api/v1/feishu/tasks", dependencies=[Depends(require_api_key)])
async def create_feishu_task(
    body: CreateTaskRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.feishu import task as feishu_task
    from app.models.database import PublishedAsset

    if not body.summary or not body.summary.strip():
        raise HTTPException(400, "summary 不能为空")

    result = await feishu_task.create_task(title=body.summary.strip())

    if body.source_task_id:
        asset = PublishedAsset(
            task_id=body.source_task_id,
            asset_type="task",
            title=body.summary.strip(),
            feishu_url=result.get("url"),
            feishu_id=result.get("task_guid"),
        )
        db.add(asset)
        await db.commit()

    return {
        "ok": True,
        "task_guid": result.get("task_guid"),
        "url": result.get("url"),
    }


@router.get("/api/v1/tasks/agents", dependencies=[Depends(require_api_key)])
async def list_agents():
    """返回所有可用 Agent 模块信息"""
    from app.agents.registry import AGENT_INFO
    return {"agents": AGENT_INFO}
