"""结果查询 API"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.models.database import Task, TaskResult, PublishedAsset, get_db
from app.models.schemas import TaskResultsResponse, AgentResultOut, ResultSection

router = APIRouter(prefix="/api/v1/tasks", tags=["results"])


@router.get(
    "/{task_id}/results",
    response_model=TaskResultsResponse,
    dependencies=[Depends(require_api_key)],
)
async def get_results(
    task_id: Annotated[str, Path(min_length=1, max_length=128)],
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")

    results_q = await db.execute(
        select(TaskResult).where(TaskResult.task_id == task_id)
    )
    task_results = results_q.scalars().all()

    assets_q = await db.execute(
        select(PublishedAsset).where(PublishedAsset.task_id == task_id)
    )
    assets = assets_q.scalars().all()

    agent_results_out = [
        AgentResultOut(
            agent_id=r.agent_id,
            agent_name=r.agent_name,
            sections=[ResultSection(**s) for s in (r.sections or [])],
            action_items=r.action_items or [],
            chart_data=r.chart_data or [],
        )
        for r in task_results
    ]

    published_assets = [
        {
            "type": a.asset_type,
            "title": a.title,
            "url": a.feishu_url,
            "id": a.feishu_id,
        }
        for a in assets
    ]

    return TaskResultsResponse(
        task_id=task_id,
        task_type_label=task.task_type_label or "",
        status=task.status,
        result_summary=task.result_summary,
        agent_results=agent_results_out,
        published_assets=published_assets,
    )
