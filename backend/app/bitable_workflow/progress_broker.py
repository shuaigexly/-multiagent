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
import threading
from collections import defaultdict
from datetime import datetime
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# task_id → list of subscriber Queues（允许多个前端同时订阅同一任务）
_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
_lock: asyncio.Lock | None = None
# 用 threading.Lock 守护 asyncio.Lock 的懒创建，防止并发首次访问产生两把锁
_init_lock = threading.Lock()


def _get_lock() -> asyncio.Lock:
    """v8.0 修复：懒初始化 race — 两个 coroutine 并发首次访问会各自创建 Lock，
    publish 用 A 锁、subscribe 用 B 锁，订阅列表完全无同步。
    用 threading.Lock 串行化"创建"这一步，asyncio.Lock 自身仍由单一实例提供异步同步。
    """
    global _lock
    if _lock is None:
        with _init_lock:
            if _lock is None:
                _lock = asyncio.Lock()
    return _lock


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
    async with _get_lock():
        queues = list(_subscribers.get(task_id, []))
    for q in queues:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            logger.debug("SSE subscriber queue full for task=%s, dropping event", task_id)


async def subscribe(task_id: str, *, keepalive_seconds: float = 15.0) -> AsyncIterator[dict]:
    """SSE 端点调用此迭代器逐条推送事件。断开时自动注销。

    v8.6.20-r9（审计 #3）：之前 `await q.get()` 无超时永久阻塞 — 客户端关浏览器
    的同时任务卡在长 LLM 调用（几分钟无 publish）→ q.get() 不返回 → finally
    清理永远不触发 → _subscribers 累积僵尸队列。加 keepalive，每 N 秒醒一次
    yield 一条 keepalive 事件让 FastAPI 检测客户端断开后跳出循环。"""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    async with _get_lock():
        _subscribers[task_id].append(q)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=keepalive_seconds)
            except asyncio.TimeoutError:
                # 心跳事件 — FastAPI 在 yield 后检查 request.is_disconnected()
                # 客户端已断开会 raise ClientDisconnect，进 finally 清理队列
                yield {
                    "task_id": task_id,
                    "event_type": "keepalive",
                    "payload": {},
                    "ts": datetime.utcnow().isoformat() + "Z",
                }
                continue
            yield msg
            if msg.get("event_type") in {"task.done", "task.error"}:
                break
    finally:
        async with _get_lock():
            if q in _subscribers.get(task_id, []):
                _subscribers[task_id].remove(q)
            if not _subscribers.get(task_id):
                _subscribers.pop(task_id, None)
