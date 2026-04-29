"""SSE 事件流：前端轮询任务进度"""
import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.core.auth import issue_stream_token, require_api_key, stream_audience_from_request, verify_stream_token
from app.core.env import get_int_env
from app.models.database import AsyncSessionLocal, Task, TaskEvent

router = APIRouter(prefix="/api/v1/tasks", tags=["events"])
logger = logging.getLogger(__name__)
MAX_SSE_SECONDS = get_int_env("MAX_SSE_SECONDS", 600, minimum=1)
STREAM_TOKEN_TTL_SECONDS = get_int_env("STREAM_TOKEN_TTL_SECONDS", 60, minimum=1)


@router.post("/{task_id}/events-token", dependencies=[Depends(require_api_key)])
async def task_events_token(task_id: str, request: Request):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Task.id).where(Task.id == task_id))
        if not result.scalar_one_or_none():
            raise HTTPException(404, "任务不存在")
    return {
        "token": issue_stream_token(
            subject=task_id,
            purpose="task-events",
            ttl_seconds=STREAM_TOKEN_TTL_SECONDS,
            audience=stream_audience_from_request(request),
        )
    }


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    request: Request,
    token: str = Query(""),
):
    """SSE 流：推送任务执行进度事件（业务语言，非技术日志）"""
    verify_stream_token(
        token,
        subject=task_id,
        purpose="task-events",
        audience=stream_audience_from_request(request),
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Task.id).where(Task.id == task_id))
        if not result.scalar_one_or_none():
            raise HTTPException(404, "任务不存在")

    return EventSourceResponse(
        _event_generator(task_id, request),
        media_type="text/event-stream",
    )


async def _event_generator(task_id: str, request: Request):
    last_seq = 0
    start_time = time.monotonic()

    while True:
        if await request.is_disconnected():
            return

        if time.monotonic() - start_time > MAX_SSE_SECONDS:
            yield {
                "data": json.dumps(
                    {"event_type": "stream.end", "status": "timeout"}
                )
            }
            break

        status = None
        async with AsyncSessionLocal() as db:
            events_result = await db.execute(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id, TaskEvent.sequence > last_seq)
                .order_by(TaskEvent.sequence)
                .limit(20)
            )
            new_events = events_result.scalars().all()

            for event in new_events:
                payload = event.payload or {}
                user_message = _to_user_message(
                    event.event_type, event.agent_name, payload
                )
                data = {
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "agent_name": event.agent_name,
                    "message": user_message,
                    "payload": payload,
                }
                yield {"data": json.dumps(data, ensure_ascii=False)}
                last_seq = event.sequence

            status_result = await db.execute(
                select(Task.status).where(Task.id == task_id)
            )
            status = status_result.scalar_one_or_none()

        if status in ("done", "failed", "cancelled"):
            yield {"data": json.dumps({"event_type": "stream.end", "status": status})}
            return

        await asyncio.sleep(1)


def _to_user_message(event_type: str, agent_name: str | None, payload: dict) -> str:
    """将技术事件类型转为用户友好的进度描述"""
    name = agent_name or ""
    if event_type == "task.recognized":
        label = payload.get("task_type_label", "")
        return f"识别任务类型：{label}"
    elif event_type == "context.retrieved":
        return payload.get("summary", "检索飞书上下文完成")
    elif event_type == "module.started":
        return f"{name} 开始分析..."
    elif event_type == "module.completed":
        return f"{name} 分析完成"
    elif event_type == "module.failed":
        return f"{name} 分析出错，已跳过"
    elif event_type == "feishu.writing":
        return payload.get("message", "正在写入飞书...")
    elif event_type == "task.done":
        return "执行完成，结果已准备好"
    elif event_type == "task.error":
        return f"执行出错：{payload.get('reason', '未知错误')}"
    else:
        return payload.get("message", event_type)
