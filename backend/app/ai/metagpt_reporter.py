"""
MetaGPTEventReporter (v2.1)
- 委托 EventEmitter，不直接写 Redis/DB
- 同时实现 report() 和 async_report()
- 文件名：metagpt_reporter.py（原 RedisReporter 已废弃）
"""
import asyncio
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.core.event_emitter import EventEmitter

logger = logging.getLogger(__name__)


def normalize_metagpt_report(name: str, value: Any, extra: Optional[dict]) -> tuple[str, dict]:
    """将 MetaGPT ResourceReporter 的 report() 参数标准化为 (event_type, payload)"""
    payload = {"name": name, "extra": extra or {}}

    if name in ("thought", "plan"):
        event_type = "agent.thought"
        payload["content"] = str(value)[:500]
    elif name in ("action", "tool_call"):
        event_type = "agent.action"
        payload["action"] = str(value)[:200]
    elif name in ("result", "observation"):
        event_type = "agent.result"
        payload["result"] = str(value)[:500]
    elif name == "message":
        event_type = "agent.message"
        payload["message"] = str(value)[:500]
    else:
        event_type = f"agent.{name}"
        payload["value"] = str(value)[:300]

    return event_type, payload


class MetaGPTEventReporter:
    """
    替代 MetaGPT ResourceReporter 的事件上报器。
    只委托给 EventEmitter，不直接操作 DB 或 Redis。
    """

    def __init__(
        self,
        task_id: str,
        agent_id: str,
        agent_name: str,
        emitter: EventEmitter,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.task_id = task_id
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.emitter = emitter
        self.loop = loop or asyncio.get_event_loop()

    def report(self, value: Any, name: str, extra: Optional[dict] = None):
        """同步调用：线程安全地调度到事件循环"""
        event_type, payload = normalize_metagpt_report(name, value, extra)
        try:
            self.loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self.emitter.emit(event_type, self.agent_id, self.agent_name, payload),
                    loop=self.loop,
                )
            )
        except Exception as e:
            logger.warning(f"MetaGPTEventReporter.report failed (non-fatal): {e}")

    async def async_report(self, value: Any, name: str, extra: Optional[dict] = None):
        """异步调用：直接 await EventEmitter"""
        event_type, payload = normalize_metagpt_report(name, value, extra)
        await self.emitter.emit(event_type, self.agent_id, self.agent_name, payload)
