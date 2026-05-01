"""v8.6.20-r43: 任务取消注册表 + /cancel 端点回归。

锁定契约：
1. cancellation.mark_cancelled / is_cancelled / raise_if_cancelled / clear_cancelled
   API 行为（单元）
2. _safe_analyze 在 task_id 已被取消时立即抛 TaskCancelled，不调 agent.analyze
3. /cancel/{record_id} 幂等：重复调返 already_pending=True
4. 端点会同步把 Bitable 主表 异常状态 标记为「用户取消」（如能拿到 app_token）
5. 端点写 record_audit 一条 workflow.cancel 事件
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
def _clean_cancellation():
    from app.bitable_workflow import cancellation
    cancellation.reset_for_tests()
    yield
    cancellation.reset_for_tests()


# ---------- 单元：cancellation.* ----------


def test_mark_cancelled_returns_true_for_new_id():
    from app.bitable_workflow import cancellation
    assert cancellation.mark_cancelled("rec_a") is True
    assert cancellation.is_cancelled("rec_a") is True


def test_mark_cancelled_idempotent_returns_false_on_second_call():
    from app.bitable_workflow import cancellation
    cancellation.mark_cancelled("rec_a")
    assert cancellation.mark_cancelled("rec_a") is False  # 已在表里


def test_mark_cancelled_strips_and_rejects_blank():
    from app.bitable_workflow import cancellation
    assert cancellation.mark_cancelled("  ") is False
    assert cancellation.mark_cancelled("") is False
    assert cancellation.mark_cancelled(None) is False
    assert cancellation.list_cancelled() == []


def test_raise_if_cancelled_throws_TaskCancelled():
    from app.bitable_workflow import cancellation
    cancellation.mark_cancelled("rec_x")
    with pytest.raises(cancellation.TaskCancelled):
        cancellation.raise_if_cancelled("rec_x")


def test_raise_if_cancelled_no_op_for_not_cancelled():
    from app.bitable_workflow import cancellation
    # Should NOT raise
    cancellation.raise_if_cancelled("rec_unrelated")


def test_clear_cancelled_removes_id_from_set():
    from app.bitable_workflow import cancellation
    cancellation.mark_cancelled("rec_a")
    assert cancellation.clear_cancelled("rec_a") is True
    assert cancellation.is_cancelled("rec_a") is False
    # 二次清掉返 False
    assert cancellation.clear_cancelled("rec_a") is False


def test_list_cancelled_returns_sorted():
    from app.bitable_workflow import cancellation
    cancellation.mark_cancelled("rec_b")
    cancellation.mark_cancelled("rec_a")
    cancellation.mark_cancelled("rec_c")
    assert cancellation.list_cancelled() == ["rec_a", "rec_b", "rec_c"]


def test_queue_size_reflects_pending_cancellations():
    from app.bitable_workflow import cancellation
    assert cancellation.queue_size() == 0
    cancellation.mark_cancelled("rec_x")
    cancellation.mark_cancelled("rec_y")
    assert cancellation.queue_size() == 2
    cancellation.clear_cancelled("rec_x")
    assert cancellation.queue_size() == 1


def test_lru_bound_evicts_oldest_when_overflow(monkeypatch):
    """v8.6.20-r46：恶意 caller 用随机 record_id 反复 mark_cancelled 不应吃满进程内存。
    超过 _MAX_SIZE → 弹出最旧条目。"""
    from app.bitable_workflow import cancellation

    cancellation.reset_for_tests()
    monkeypatch.setattr(cancellation, "_MAX_SIZE", 3)

    cancellation.mark_cancelled("oldest")
    cancellation.mark_cancelled("middle_a")
    cancellation.mark_cancelled("middle_b")
    cancellation.mark_cancelled("newest")  # 触发 evict oldest

    assert cancellation.queue_size() == 3
    assert cancellation.is_cancelled("oldest") is False  # 被 LRU 弹出
    assert cancellation.is_cancelled("newest") is True
    assert cancellation.is_cancelled("middle_a") is True
    assert cancellation.is_cancelled("middle_b") is True


def test_lru_bound_does_not_evict_when_below_capacity(monkeypatch):
    from app.bitable_workflow import cancellation

    cancellation.reset_for_tests()
    monkeypatch.setattr(cancellation, "_MAX_SIZE", 100)

    for i in range(50):
        cancellation.mark_cancelled(f"rec_{i}")

    # 50 条全部留在表内
    assert cancellation.queue_size() == 50
    assert cancellation.is_cancelled("rec_0") is True
    assert cancellation.is_cancelled("rec_49") is True


# ---------- _safe_analyze 与 cancellation 的集成 ----------


@pytest.mark.asyncio
async def test_safe_analyze_raises_when_task_cancelled(monkeypatch):
    from app.agents import circuit_breaker
    from app.agents.base_agent import AgentResult, ResultSection
    from app.bitable_workflow import cancellation, workflow_agents

    circuit_breaker.reset()
    cancellation.reset_for_tests()
    cancellation.mark_cancelled("rec_cancel_me")

    analyze_calls: list = []

    class _Agent:
        agent_id = "data_analyst"
        agent_name = "数据分析师"

        async def analyze(self, **kwargs):
            analyze_calls.append(kwargs)
            return AgentResult(
                agent_id="data_analyst", agent_name="数据分析师",
                sections=[ResultSection(title="x", content="不该被调到")],
                action_items=[], raw_output="OK", confidence_hint=4,
            )

    async def fake_get(*_a, **_kw):
        return None

    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_cached_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_shared_result", fake_get)

    with pytest.raises(cancellation.TaskCancelled):
        await workflow_agents._safe_analyze(
            _Agent(),
            "test task",
            upstream=[],
            data_summary=None,
            task_id="rec_cancel_me",
            dimension="测试",
        )

    # agent.analyze 必须没被调用
    assert analyze_calls == []


# ---------- 端点 /cancel/{record_id} ----------


@pytest.mark.asyncio
async def test_cancel_endpoint_marks_record_and_returns_status(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops, cancellation

    cancellation.reset_for_tests()

    update_calls: list = []

    async def fake_update(_app, _tid, _rid, fields, optional_keys=None):
        update_calls.append({"fields": fields})

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()
    workflow._set_state(
        "app_a",
        app_token="app_a",
        table_ids={"task": "tbl_task"},
    )

    resp = await workflow.workflow_cancel_task(record_id="rec_xxx", app_token="app_a")

    assert resp["cancelled"] is True
    assert resp["already_pending"] is False
    assert resp["bitable_marked"] is True
    assert resp["queue_size"] >= 1
    # Bitable 写了「异常状态」+「异常类型」
    assert update_calls
    fields_written = update_calls[0]["fields"]
    assert fields_written["异常类型"] == "用户取消"
    # cancellation 集合里有这条
    assert cancellation.is_cancelled("rec_xxx")


@pytest.mark.asyncio
async def test_cancel_endpoint_idempotent(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops, cancellation

    cancellation.reset_for_tests()

    async def fake_update(*_a, **_kw):
        return None

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()
    workflow._set_state(
        "app_idempotent",
        app_token="app_idempotent",
        table_ids={"task": "tbl_task"},
    )

    first = await workflow.workflow_cancel_task(record_id="rec_dup", app_token="app_idempotent")
    second = await workflow.workflow_cancel_task(record_id="rec_dup", app_token="app_idempotent")

    assert first["already_pending"] is False
    assert second["already_pending"] is True
    # 两次都返 cancelled=True
    assert second["cancelled"] is True


@pytest.mark.asyncio
async def test_cancel_endpoint_works_without_app_token(monkeypatch):
    """没传 app_token 也能 mark cancellation；只是不 mark Bitable。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import cancellation

    cancellation.reset_for_tests()

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()

    resp = await workflow.workflow_cancel_task(record_id="rec_solo", app_token=None)
    assert resp["cancelled"] is True
    assert resp["bitable_marked"] is False
    assert cancellation.is_cancelled("rec_solo")
