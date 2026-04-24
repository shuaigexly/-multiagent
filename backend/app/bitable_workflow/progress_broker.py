"""进程内 SSE 进度广播（无需外部依赖）。

scheduler 里的 Wave 进度回调会 publish 事件，/api/v1/workflow/stream/{task_id}
的 SSE 端点从对应队列消费并推给前端。

设计要点：
- 按 task_id 隔离队列，互不干扰
- 订阅者断开时自动回收队列，无泄漏
- 单进程内存，够单机场景；集群部署需换成 Redis pub/sub
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# task_id → list of subscriber Queues（允许多个前端同时订阅同一任务）
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
_lock = asyncio.Lock()


async def publish(task_id: str, event_type: str, payload: dict) -> None:
    """向订阅 task_id 的所有 SSE 连接广播一条事件。"""
    if not task_id:
        return
    msg = {
        "task_id": task_id,
        "event_type": event_type,
        "payload": payload,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    async with _lock:
        queues = list(_subscribers.get(task_id, []))
    for q in queues:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            logger.debug("SSE subscriber queue full for task=%s, dropping event", task_id)


async def subscribe(task_id: str) -> AsyncIterator[dict]:
    """SSE 端点调用此迭代器逐条推送事件。断开时自动注销。"""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with _lock:
        _subscribers[task_id].append(q)
    try:
        while True:
            msg = await q.get()
            yield msg
            if msg.get("event_type") in {"task.done", "task.error"}:
                break
    finally:
        async with _lock:
            if q in _subscribers.get(task_id, []):
                _subscribers[task_id].remove(q)
            if not _subscribers.get(task_id):
                _subscribers.pop(task_id, None)
