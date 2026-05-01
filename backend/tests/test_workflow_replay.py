"""v8.6.20-r44: /replay/{record_id} 复跑端点回归。

锁定契约：
1. in-flight (状态=分析中) 的任务 → 409，不允许覆盖
2. 已完成 / 已取消 / 已归档的任务 → 拉回「待分析」+ 清异常字段
3. cancellation 注册表里的标记被清除（cancel → fix → replay 链路成立）
4. ?fresh=true 触发 invalidate_task_cache 清 Redis 缓存
5. record_audit 写一条 workflow.replay 事件
6. base 未 setup → 409；记录不存在 → 404
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
def _clean_state(monkeypatch):
    from app.api import workflow
    from app.bitable_workflow import cancellation

    cancellation.reset_for_tests()
    workflow._state.clear()
    workflow._state_by_token.clear()
    workflow._active_token = ""
    yield
    cancellation.reset_for_tests()
    workflow._state.clear()
    workflow._state_by_token.clear()
    workflow._active_token = ""


def _setup_active_base(workflow):
    workflow._set_state(
        "app_replay",
        app_token="app_replay",
        table_ids={"task": "tbl_task"},
    )


@pytest.mark.asyncio
async def test_replay_completed_task_resets_status_to_pending(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    update_calls: list = []

    async def fake_get(_app, _tid, _rid):
        return {"fields": {"状态": "已完成", "异常状态": "", "进度": 1.0}}

    async def fake_update(_app, _tid, _rid, fields, optional_keys=None):
        update_calls.append({"fields": fields})

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "get_record", fake_get)
    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)
    _setup_active_base(workflow)

    resp = await workflow.workflow_replay_task(
        record_id="rec_done", app_token="app_replay", fresh=False,
    )

    assert resp["replayed"] is True
    assert resp["previous_status"] == "已完成"
    assert resp["fresh"] is False
    assert resp["cache_entries_cleared"] == 0
    # update 的字段：状态=待分析 + 进度=0 + 清异常
    assert update_calls
    written = update_calls[0]["fields"]
    assert written["状态"] == "待分析"
    assert written["进度"] == 0.0
    assert written["异常状态"] == ""
    assert written["异常类型"] == ""


@pytest.mark.asyncio
async def test_replay_in_flight_task_rejected_with_409(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops
    from fastapi import HTTPException

    async def fake_get(_app, _tid, _rid):
        return {"fields": {"状态": "分析中"}}

    monkeypatch.setattr(bitable_ops, "get_record", fake_get)
    _setup_active_base(workflow)

    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_replay_task(
            record_id="rec_running", app_token="app_replay", fresh=False,
        )
    assert exc.value.status_code == 409
    assert "分析中" in exc.value.detail


@pytest.mark.asyncio
async def test_replay_clears_cancellation_marker(monkeypatch):
    """cancel → fix → replay 链路：replay 必须把 cancellation 注册表清掉，
    否则下一轮 cycle 接手立刻又被 raise_if_cancelled 抛 TaskCancelled。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops, cancellation

    async def fake_get(_app, _tid, _rid):
        return {"fields": {"状态": "已归档"}}

    async def fake_update(*_a, **_kw):
        return None

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "get_record", fake_get)
    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)
    _setup_active_base(workflow)

    cancellation.mark_cancelled("rec_was_cancelled")
    assert cancellation.is_cancelled("rec_was_cancelled") is True

    await workflow.workflow_replay_task(
        record_id="rec_was_cancelled", app_token="app_replay", fresh=False,
    )

    # replay 后 cancellation 必须被清
    assert cancellation.is_cancelled("rec_was_cancelled") is False


@pytest.mark.asyncio
async def test_replay_fresh_mode_invalidates_task_cache(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import agent_cache, bitable_ops

    async def fake_get(_app, _tid, _rid):
        return {"fields": {"状态": "已完成"}}

    async def fake_update(*_a, **_kw):
        return None

    async def fake_record_audit(*_a, **_kw):
        return None

    cleared_for: list = []

    async def fake_invalidate(task_id):
        cleared_for.append(task_id)
        return 7  # 假装清了 7 个 agent 缓存

    monkeypatch.setattr(bitable_ops, "get_record", fake_get)
    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)
    monkeypatch.setattr(agent_cache, "invalidate_task_cache", fake_invalidate)
    _setup_active_base(workflow)

    resp = await workflow.workflow_replay_task(
        record_id="rec_fresh", app_token="app_replay", fresh=True,
    )

    assert cleared_for == ["rec_fresh"]
    assert resp["fresh"] is True
    assert resp["cache_entries_cleared"] == 7


@pytest.mark.asyncio
async def test_replay_default_does_not_invalidate_cache(monkeypatch):
    """默认 fresh=False：能复用 agent_cache 就复用，省 LLM tokens。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import agent_cache, bitable_ops

    async def fake_get(_app, _tid, _rid):
        return {"fields": {"状态": "已完成"}}

    async def fake_update(*_a, **_kw):
        return None

    async def fake_record_audit(*_a, **_kw):
        return None

    invalidate_calls: list = []

    async def fake_invalidate(task_id):
        invalidate_calls.append(task_id)
        return 7

    monkeypatch.setattr(bitable_ops, "get_record", fake_get)
    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)
    monkeypatch.setattr(agent_cache, "invalidate_task_cache", fake_invalidate)
    _setup_active_base(workflow)

    await workflow.workflow_replay_task(
        record_id="rec_no_fresh", app_token="app_replay", fresh=False,
    )
    # 默认不清缓存
    assert invalidate_calls == []


@pytest.mark.asyncio
async def test_replay_returns_404_when_record_does_not_exist(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops
    from fastapi import HTTPException

    async def fail_get(*_a, **_kw):
        raise RuntimeError("RecordNotFound 1254043")

    monkeypatch.setattr(bitable_ops, "get_record", fail_get)
    _setup_active_base(workflow)

    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_replay_task(
            record_id="rec_ghost", app_token="app_replay", fresh=False,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_replay_returns_409_when_base_not_setup(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from fastapi import HTTPException

    # 不调 _setup_active_base
    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_replay_task(
            record_id="rec_x", app_token=None, fresh=False,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_replay_writes_audit_event(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    async def fake_get(_app, _tid, _rid):
        return {"fields": {"状态": "已完成"}}

    async def fake_update(*_a, **_kw):
        return None

    audit_events: list = []

    async def fake_record_audit(action, *, target=None, payload=None, **_kw):
        audit_events.append({"action": action, "target": target, "payload": payload})

    monkeypatch.setattr(bitable_ops, "get_record", fake_get)
    monkeypatch.setattr(bitable_ops, "update_record_optional_fields", fake_update)
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)
    _setup_active_base(workflow)

    await workflow.workflow_replay_task(
        record_id="rec_audit", app_token="app_replay", fresh=False,
    )

    assert len(audit_events) == 1
    assert audit_events[0]["action"] == "workflow.replay"
    assert audit_events[0]["target"] == "rec_audit"
    assert audit_events[0]["payload"]["previous_status"] == "已完成"
