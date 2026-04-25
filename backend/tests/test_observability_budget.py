"""新增 observability + budget 模块的单元测试（不依赖 FastAPI/Starlette）。"""
import asyncio

import pytest

from app.core.budget import (
    BudgetExceeded,
    BudgetStatus,
    check_budget,
    get_status,
    record_usage,
)
from app.core.observability import (
    _agent_id,
    _correlation_id,
    _task_id,
    correlation_scope,
    get_correlation_id,
    get_task_id,
    set_task_context,
)
from app.core.settings import settings


@pytest.mark.asyncio
async def test_correlation_scope_sets_and_clears_context():
    assert get_correlation_id() is None
    async with correlation_scope("abc-123") as cid:
        assert cid == "abc-123"
        assert get_correlation_id() == "abc-123"
        set_task_context(task_id="t-1", agent_id="data_analyst")
        assert get_task_id() == "t-1"
    # scope 退出后清空
    assert get_correlation_id() is None
    assert get_task_id() is None


@pytest.mark.asyncio
async def test_correlation_scope_auto_generates_id():
    async with correlation_scope() as cid:
        assert isinstance(cid, str) and len(cid) >= 8


@pytest.mark.asyncio
async def test_record_usage_accumulates_per_task(monkeypatch):
    # 把 Redis 关闭，使用 in-memory backend 以保证测试隔离
    monkeypatch.setattr("app.core.budget._redis_retry_at", float("inf"))
    async with correlation_scope("test"):
        set_task_context(task_id="task-budget-1", tenant_id="tenantA")
        first = await record_usage(prompt_tokens=100, completion_tokens=50)
        second = await record_usage(prompt_tokens=200, completion_tokens=100)
        # task 累计 = 100+50 + 200+100 = 450
        assert first == 150
        assert second == 450


@pytest.mark.asyncio
async def test_check_budget_strict_raises_on_overrun(monkeypatch):
    monkeypatch.setattr("app.core.budget._redis_retry_at", float("inf"))
    monkeypatch.setattr(settings, "per_task_token_budget", 100)
    async with correlation_scope("test"):
        set_task_context(task_id="task-overrun", tenant_id="tenantB")
        await record_usage(prompt_tokens=80, completion_tokens=30)  # 110 > 100
        with pytest.raises(BudgetExceeded):
            await check_budget(strict=True)


@pytest.mark.asyncio
async def test_check_budget_returns_status_when_not_strict(monkeypatch):
    monkeypatch.setattr("app.core.budget._redis_retry_at", float("inf"))
    monkeypatch.setattr(settings, "per_task_token_budget", 50)
    async with correlation_scope("test"):
        set_task_context(task_id="task-soft", tenant_id="tenantC")
        await record_usage(prompt_tokens=40, completion_tokens=20)  # 60 > 50
        status = await check_budget(strict=False)
        assert isinstance(status, BudgetStatus)
        assert status.exceeded is True
        assert status.scope == "task"


@pytest.mark.asyncio
async def test_get_status_returns_task_and_tenant_views(monkeypatch):
    monkeypatch.setattr("app.core.budget._redis_retry_at", float("inf"))
    async with correlation_scope("test"):
        set_task_context(task_id="task-view", tenant_id="tenantD")
        await record_usage(prompt_tokens=10, completion_tokens=5)
        s = await get_status()
        assert "task" in s
        assert s["task"]["used"] >= 15
        assert "tenant_today" in s
        assert s["tenant_today"]["id"] == "tenantD"
        assert "global_today" in s
