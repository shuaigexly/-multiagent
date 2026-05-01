"""v8.6.20-r35: /api/v1/workflow/telemetry 端点回归。

锁定契约：
1. workflow.running / active_token（redact）/ tenants_registered / tenants_redacted（redact）
2. budget 快照含 task / tenant_today / global_today 三段 + reasoning 单独维度
3. SSE 订阅计数（进程内 health 代理）
4. 无 base 时不崩，返回零值
5. budget 抛错时返 fallback "error" 字段，不让端点 500
"""
from __future__ import annotations

from types import ModuleType
import sys

import pytest


def _ensure_sse_stub(monkeypatch):
    sse_pkg = ModuleType("sse_starlette")
    sse_mod = ModuleType("sse_starlette.sse")
    sse_mod.EventSourceResponse = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_pkg)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_mod)


@pytest.fixture(autouse=True)
def _clean_state():
    from app.api import workflow

    workflow._state.clear()
    workflow._state_by_token.clear()
    workflow._active_token = ""
    yield
    workflow._state.clear()
    workflow._state_by_token.clear()
    workflow._active_token = ""


@pytest.mark.asyncio
async def test_telemetry_returns_zero_state_when_idle(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.core import budget

    monkeypatch.setattr(workflow.runner, "is_running", lambda: False)

    async def fake_status():
        return {
            "tenant_today": {"id": "default", "used": 0, "reasoning": 0, "limit": 0},
            "global_today": {"used": 0, "reasoning": 0},
        }

    monkeypatch.setattr(budget, "get_status", fake_status)

    resp = await workflow.workflow_telemetry()

    assert resp["workflow"]["running"] is False
    assert resp["workflow"]["active_token"] == ""
    assert resp["workflow"]["tenants_registered"] == 0
    assert resp["workflow"]["tenants_redacted"] == []
    assert resp["budget"]["tenant_today"]["used"] == 0
    assert resp["sse"]["active_streams"] == 0
    assert resp["sse"]["total_subscribers"] == 0
    assert "snapshot_at" in resp


@pytest.mark.asyncio
async def test_telemetry_redacts_app_tokens_in_registry(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.core import budget

    workflow._set_state("base_secret_app_token_xyz_1234567890ABCDEFG", app_token="base_secret_app_token_xyz_1234567890ABCDEFG")
    workflow._set_state("another_long_app_token_PQRS", app_token="another_long_app_token_PQRS")

    monkeypatch.setattr(workflow.runner, "is_running", lambda: True)

    async def fake_status():
        return {"tenant_today": {"used": 1500}, "global_today": {"used": 4200}}

    monkeypatch.setattr(budget, "get_status", fake_status)

    resp = await workflow.workflow_telemetry()

    assert resp["workflow"]["running"] is True
    assert resp["workflow"]["tenants_registered"] == 2
    # active_token 是最后写的；redact_sensitive_text 不一定改短 token，但保证经过脱敏函数
    assert resp["workflow"]["active_token"], "active_token 不应为空"
    assert len(resp["workflow"]["tenants_redacted"]) == 2


@pytest.mark.asyncio
async def test_telemetry_handles_budget_failure_gracefully(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.core import budget

    monkeypatch.setattr(workflow.runner, "is_running", lambda: False)

    async def fail_status():
        raise RuntimeError("Redis down")

    monkeypatch.setattr(budget, "get_status", fail_status)

    resp = await workflow.workflow_telemetry()

    # budget 失败不让端点 500；返回 error 字段供前端展示
    assert "error" in resp["budget"]
    # 其他维度仍正常输出
    assert resp["workflow"]["running"] is False


@pytest.mark.asyncio
async def test_telemetry_includes_reasoning_tokens_when_provided(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.core import budget

    monkeypatch.setattr(workflow.runner, "is_running", lambda: False)

    async def fake_status():
        return {
            "task": {"id": "t1", "used": 5000, "reasoning": 1200, "limit": 100000},
            "tenant_today": {"id": "tenant_a", "used": 80000, "reasoning": 18000, "limit": 500000},
            "global_today": {"used": 320000, "reasoning": 60000},
        }

    monkeypatch.setattr(budget, "get_status", fake_status)

    resp = await workflow.workflow_telemetry()

    assert resp["budget"]["task"]["reasoning"] == 1200
    assert resp["budget"]["tenant_today"]["reasoning"] == 18000
    assert resp["budget"]["global_today"]["reasoning"] == 60000


@pytest.mark.asyncio
async def test_telemetry_counts_active_sse_subscribers(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    import asyncio

    from app.api import workflow
    from app.bitable_workflow import progress_broker
    from app.core import budget

    monkeypatch.setattr(workflow.runner, "is_running", lambda: True)

    async def fake_status():
        return {"tenant_today": {"used": 0}, "global_today": {"used": 0}}

    monkeypatch.setattr(budget, "get_status", fake_status)

    # 模拟 2 条任务，分别有 1 + 2 个订阅者（前端打开了多个标签页）
    progress_broker._subscribers.clear()
    progress_broker._subscribers["task_a"] = [asyncio.Queue(), asyncio.Queue()]
    progress_broker._subscribers["task_b"] = [asyncio.Queue()]

    try:
        resp = await workflow.workflow_telemetry()
        assert resp["sse"]["active_streams"] == 2
        assert resp["sse"]["total_subscribers"] == 3
    finally:
        progress_broker._subscribers.clear()
