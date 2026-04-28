"""审计日志：以 append-only 方式记录系统级敏感操作（启停调度、配置变更、OAuth 等）。

设计原则：
  - 任何一次 record_audit 都以新行写入，不允许更新/删除（DB 层不加 UPDATE 接口）
  - 写入失败仅 warning，绝不阻塞业务流程
  - actor 可以是 "user:<open_id>" / "system" / "feishu_bot" / "scheduler"
  - target 是被操作对象 ID（task_id / app_token / user_config 等）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.core.observability import get_correlation_id, get_tenant_id
from app.models.database import AsyncSessionLocal, AuditLog

logger = logging.getLogger(__name__)


# v8.6.20-r13（审计 #9 安全）：审计日志 payload 是 JSON 列，明文存。OAuth 回调、
# 配置更新等 action 的 payload 可能含 OAuth `code` / `app_secret` /
# `refresh_token` / `access_token` / `password` 等敏感原值；任何能读 audit_log
# 表的工具都直接看到。在写入前递归 redact 一遍。
_SENSITIVE_KEY_TOKENS = (
    "secret",
    "password",
    "passwd",
    "token",
    "code",
    "key",
    "credential",
    "session",
)


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    k = key.lower()
    # 白名单：明显非敏感的"key"含义字段不要误伤
    if k in {"key_field", "primary_key", "task_key", "cache_key", "code_block", "actor_key", "lookup_key"}:
        return False
    return any(token in k for token in _SENSITIVE_KEY_TOKENS)


def _redact_payload(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[REDACTED:depth]"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _is_sensitive_key(k):
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact_payload(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_redact_payload(item, depth + 1) for item in value[:50]]
    if isinstance(value, tuple):
        return [_redact_payload(item, depth + 1) for item in value[:50]]
    return value


async def record_audit(
    action: str,
    *,
    actor: str = "system",
    target: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    result: str = "ok",
) -> None:
    """记一条审计日志。

    action 命名规范（动名词 + 资源）：
      "workflow.setup" / "workflow.start" / "workflow.stop" /
      "workflow.seed" / "config.update" / "oauth.callback" /
      "task.cancel" / "task.delete" 等
    """
    try:
        safe_payload = _redact_payload(payload) if payload else {}
        async with AsyncSessionLocal() as db:
            entry = AuditLog(
                action=action,
                actor=actor,
                target=target or "",
                tenant_id=get_tenant_id() or "",
                correlation_id=get_correlation_id() or "",
                payload=safe_payload,
                result=result,
            )
            db.add(entry)
            await db.commit()
    except Exception as exc:
        # 审计写入失败永不阻塞业务，但需打日志便于追查
        logger.warning(
            "Audit log write failed: action=%s target=%s err=%s",
            action, target, exc,
        )
