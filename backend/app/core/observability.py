"""企业级可观测性：结构化 JSON 日志 + correlation_id 跨任务传播。

所有 logger.info/warning/error 自动带上当前上下文：
  - correlation_id：贯穿一次任务/请求的全链路追踪 ID
  - task_id：任务标识
  - agent_id：当前 agent
  - tenant_id：租户标识（多租户演进预留）

通过 ContextVar 实现，无需改动现有日志调用。

使用：
  >>> from app.core.observability import correlation_scope, set_task_context
  >>> async with correlation_scope("task-abc"):
  ...     set_task_context(task_id="abc", agent_id="ceo")
  ...     logger.info("Wave1 complete")  # 自动包含 correlation_id/task_id/agent_id
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# Context variables — 跨 await 边界传播
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)
_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("task_id", default=None)
_agent_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("agent_id", default=None)
_tenant_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("tenant_id", default=None)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def get_task_id() -> str | None:
    return _task_id.get()


def get_agent_id() -> str | None:
    return _agent_id.get()


def get_tenant_id() -> str | None:
    return _tenant_id.get()


def set_task_context(
    *,
    task_id: str | None = None,
    agent_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """设置当前 asyncio task / 线程的执行上下文。"""
    if task_id is not None:
        _task_id.set(task_id)
    if agent_id is not None:
        _agent_id.set(agent_id)
    if tenant_id is not None:
        _tenant_id.set(tenant_id)


def clear_task_context(
    *,
    task_id: bool = False,
    agent_id: bool = False,
    tenant_id: bool = False,
) -> None:
    """Clear selected ContextVar fields in the current asyncio context."""
    if task_id:
        _task_id.set(None)
    if agent_id:
        _agent_id.set(None)
    if tenant_id:
        _tenant_id.set(None)


@asynccontextmanager
async def correlation_scope(correlation_id: str | None = None) -> AsyncIterator[str]:
    """绑定 correlation_id 到当前 asyncio context；离开 scope 自动清除。

    若未提供 correlation_id 则自动生成 uuid4 短码（前 12 位）。
    """
    cid = correlation_id or uuid.uuid4().hex[:12]
    token = _correlation_id.set(cid)
    task_token = _task_id.set(None)
    agent_token = _agent_id.set(None)
    tenant_token = _tenant_id.set(None)
    try:
        yield cid
    finally:
        _correlation_id.reset(token)
        _task_id.reset(task_token)
        _agent_id.reset(agent_token)
        _tenant_id.reset(tenant_token)


class _ContextFilter(logging.Filter):
    """注入 ContextVar 值到每条 LogRecord，供 formatter 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or "-"
        record.task_id = _task_id.get() or "-"
        record.agent_id = _agent_id.get() or "-"
        record.tenant_id = _tenant_id.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    """Structured JSON output — 适合 Loki / Datadog / CloudWatch 直接消费。"""

    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%f%z") or time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
            "task_id": getattr(record, "task_id", "-"),
            "agent_id": getattr(record, "agent_id", "-"),
            "tenant_id": getattr(record, "tenant_id", "-"),
        }
        # Forward extra={...} fields if any
        for key, val in record.__dict__.items():
            if key.startswith("_") or key in {
                "args", "msg", "name", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "message", "asctime",
                "correlation_id", "task_id", "agent_id", "tenant_id",
            }:
                continue
            try:
                json.dumps(val, default=str)
                base[key] = val
            except Exception:
                base[key] = repr(val)
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False, default=str)


class _PlainFormatter(logging.Formatter):
    """Human-readable fallback for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s [cid=%(correlation_id)s task=%(task_id)s agent=%(agent_id)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def configure_logging() -> None:
    """安装结构化日志 handler。环境变量 LOG_FORMAT=json|plain（默认 plain）。"""
    fmt = os.getenv("LOG_FORMAT", "plain").lower()
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if fmt == "json" else _PlainFormatter())
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    # 清掉 basicConfig 旧 handler，避免重复输出
    root.handlers = [handler]
    root.setLevel(level)

    # 抑制三方过吵库
    for noisy in ("httpx", "httpcore", "openai._base_client", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
