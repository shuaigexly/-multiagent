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
        async with AsyncSessionLocal() as db:
            entry = AuditLog(
                action=action,
                actor=actor,
                target=target or "",
                tenant_id=get_tenant_id() or "",
                correlation_id=get_correlation_id() or "",
                payload=payload or {},
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
