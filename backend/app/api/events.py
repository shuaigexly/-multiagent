"""SSE 事件流：前端轮询任务进度"""
import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.models.database import Task, TaskEvent, get_db

router = APIRouter(prefix="/api/v1/tasks", tags=["events"])
logger = logging.getLogger(__name__)


@router.get("/{task_id}/events")
async def task_events(task_id: str, db: AsyncSession = Depends(get_db)):
    """SSE 流：推送任务执行进度事件（业务语言，非技术日志）"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")

    return EventSourceResponse(
        _event_generator(task_id, db),
        media_type="text/event-stream",
    )


async def _event_generator(task_id: str, db: AsyncSession) -> AsyncIterator[dict]:
    last_seq = 0
    max_polls = 300   # 最多轮询 5 分钟（每秒一次）

    for _ in range(max_polls):
        result = await db.execute(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id, TaskEvent.sequence > last_seq)
            .order_by(TaskEvent.sequence)
            .limit(20)
        )
        events = result.scalars().all()

        for event in events:
            payload = event.payload or {}
            # 将 event_type 转成用户友好的消息
            user_message = _to_user_message(event.event_type, event.agent_name, payload)
            data = {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "agent_name": event.agent_name,
                "message": user_message,
                "payload": payload,
            }
            yield {"data": json.dumps(data, ensure_ascii=False)}
            last_seq = event.sequence

        # 检查任务是否完成
        task_result = await db.execute(
            select(Task.status).where(Task.id == task_id)
        )
        status = task_result.scalar_one_or_none()
        if status in ("done", "failed"):
            yield {"data": json.dumps({"event_type": "stream.end", "status": status})}
            return

        await asyncio.sleep(1)

    yield {"data": json.dumps({"event_type": "stream.timeout"})}


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
