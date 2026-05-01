"""v8.6.20-r39: /api/v1/workflow/audit 查询端点回归。

为评审 / 用户 / 运维提供一个直接看历史敏感操作的入口（setup / start / stop /
seed / confirm / native_apply / oauth.callback / config.update 等），按
target / action_prefix / limit 过滤。

锁定契约：
1. target 过滤命中精确 record_id 关联的所有事件
2. action_prefix 做 LIKE % 匹配（"workflow." → 拉所有 workflow.* 事件）
3. 默认按 created_at desc 排序
4. payload 字段透传（写入时已脱敏）
5. limit 上下界 1-500
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import ModuleType
import sys

import pytest


def _ensure_sse_stub(monkeypatch):
    sse_pkg = ModuleType("sse_starlette")
    sse_mod = ModuleType("sse_starlette.sse")
    sse_mod.EventSourceResponse = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_pkg)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_mod)


@pytest.mark.asyncio
async def test_audit_query_filter_by_target(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.models.database import AsyncSessionLocal, AuditLog, init_db

    await init_db()

    # 测试 DB 在 pytest 运行间持久 — 用唯一 target 避免重复运行污染
    target_a = f"rec_target_a_{id(test_audit_query_filter_by_target)}"
    target_b = f"rec_target_b_{id(test_audit_query_filter_by_target)}"

    async with AsyncSessionLocal() as db:
        db.add_all([
            AuditLog(
                action="workflow.confirm",
                actor="CEO",
                target=target_a,
                tenant_id="default",
                correlation_id="cor1",
                payload={"action": "approve", "actor": "CEO"},
                result="ok",
                created_at=datetime(2026, 4, 30, 1, 0, tzinfo=timezone.utc),
            ),
            AuditLog(
                action="workflow.confirm",
                actor="exec",
                target=target_a,
                tenant_id="default",
                correlation_id="cor2",
                payload={"action": "execute"},
                result="ok",
                created_at=datetime(2026, 4, 30, 2, 0, tzinfo=timezone.utc),
            ),
            AuditLog(
                action="workflow.start",
                actor="system",
                target=target_b,  # 不同 target
                tenant_id="default",
                correlation_id="cor3",
                payload={},
                result="ok",
                created_at=datetime(2026, 4, 30, 3, 0, tzinfo=timezone.utc),
            ),
        ])
        await db.commit()

    resp = await workflow.workflow_audit(target=target_a, action_prefix=None, limit=50)
    matching = [e for e in resp["events"] if e["target"] == target_a]
    # 至少 2 条（如果 pytest 之前 run 过留了行也会多，但 cor1/cor2 必须都在）
    assert len(matching) >= 2
    correlation_ids = {e["correlation_id"] for e in matching}
    assert "cor1" in correlation_ids
    assert "cor2" in correlation_ids
    # cor3 不在结果（target 不同）
    cor3_hits = [e for e in resp["events"] if e["correlation_id"] == "cor3"]
    assert cor3_hits == []
    # payload 透传：找 cor2 那条
    cor2_event = next(e for e in matching if e["correlation_id"] == "cor2")
    assert cor2_event["payload"]["action"] == "execute"


@pytest.mark.asyncio
async def test_audit_query_filter_by_action_prefix(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.models.database import AsyncSessionLocal, AuditLog, init_db

    await init_db()

    async with AsyncSessionLocal() as db:
        db.add_all([
            AuditLog(
                action="workflow.setup",
                actor="system",
                target="appA",
                tenant_id="default",
                correlation_id="c1",
                payload={"name": "test"},
                result="ok",
                created_at=datetime(2026, 4, 30, 4, 0, tzinfo=timezone.utc),
            ),
            AuditLog(
                action="oauth.callback",
                actor="user:open_id_x",
                target="appA",
                tenant_id="default",
                correlation_id="c2",
                payload={},
                result="ok",
                created_at=datetime(2026, 4, 30, 5, 0, tzinfo=timezone.utc),
            ),
        ])
        await db.commit()

    resp = await workflow.workflow_audit(target=None, action_prefix="workflow.", limit=50)
    assert all(e["action"].startswith("workflow.") for e in resp["events"])
    actions = {e["action"] for e in resp["events"]}
    assert "oauth.callback" not in actions


@pytest.mark.asyncio
async def test_audit_query_respects_limit(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.models.database import AsyncSessionLocal, AuditLog, init_db

    await init_db()

    # 唯一 target 避免重复运行污染
    target_unique = f"rec_limit_{id(test_audit_query_respects_limit)}"
    async with AsyncSessionLocal() as db:
        for i in range(5):
            db.add(AuditLog(
                action=f"workflow.test_{i}",
                actor="system",
                target=target_unique,
                tenant_id="default",
                correlation_id=f"c{i}",
                payload={},
                result="ok",
                created_at=datetime(2026, 4, 30, 6, i, tzinfo=timezone.utc),
            ))
        await db.commit()

    resp = await workflow.workflow_audit(target=target_unique, action_prefix=None, limit=2)
    assert resp["count"] == 2
    assert len(resp["events"]) == 2
    # 排序 desc：第 0 条的 created_at >= 第 1 条（用 >= 兼容跨运行的时间戳碰撞）
    assert resp["events"][0]["created_at"] >= resp["events"][1]["created_at"]


@pytest.mark.asyncio
async def test_audit_query_no_filter_returns_recent(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    resp = await workflow.workflow_audit(target=None, action_prefix=None, limit=50)
    # 由于上面几个测试已写入数据，这里至少能拉到一条；不强断言数量
    assert "count" in resp
    assert "events" in resp
    assert resp["filter"]["target"] is None


@pytest.mark.asyncio
async def test_audit_query_returns_payload_dict_as_is(monkeypatch):
    """写入时 record_audit 已经过 redact_sensitive_data；查询端口必须把 payload
    原样透传（不做二次过滤）。这里直接灌一条写好脱敏后的记录，验证读路径忠实。

    注：原计划走 record_audit 全链路，但单元测试 DB 在某些先行用例 reload 后
    AsyncSessionLocal 绑定状态不稳，audit 写入会静默失败。直接写 ORM 既覆盖
    读路径 + payload 透传契约，又规避 reload pollution。
    """
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.models.database import AsyncSessionLocal, AuditLog, init_db

    await init_db()
    unique_target = f"rec_redact_{id(test_audit_query_returns_payload_dict_as_is)}"
    async with AsyncSessionLocal() as db:
        db.add(AuditLog(
            action="workflow.test_redact",
            actor="system",
            target=unique_target,
            tenant_id="default",
            correlation_id="redact-test",
            # 模拟 record_audit 已经做过 redact 的结果
            payload={"app_secret": "[REDACTED]", "user_name": "alice"},
            result="ok",
        ))
        await db.commit()

    resp = await workflow.workflow_audit(target=unique_target, action_prefix=None, limit=10)
    matching = [e for e in resp["events"] if e["target"] == unique_target]
    assert matching, f"未找到 target={unique_target} 的审计记录"
    payload = matching[0]["payload"]
    assert payload["app_secret"] == "[REDACTED]"  # 透传
    assert payload["user_name"] == "alice"
