"""v8.6.20-r45: /agents catalog + /agents/{id}/profile 端点回归。

锁定契约：
1. /agents 返回 7 个岗位 + 各自 downstream_dependencies / 技能数 / hint 数 / 熔断态
2. /agents/{id}/profile 返回详细画像 + 技能元数据 + 模型配置
3. 不存在的 agent_id → 404
4. fetch_active_hints / get_skills_for_agent 抛错时端点不 500，graceful 降级
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
def _reset_breakers():
    from app.agents import circuit_breaker
    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


@pytest.mark.asyncio
async def test_agents_catalog_returns_seven_agents(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    async def empty_hints(_aid):
        return []

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", empty_hints)

    resp = await workflow.workflow_agents_catalog()
    assert resp["count"] == 7
    aids = {a["id"] for a in resp["agents"]}
    assert aids == {
        "data_analyst", "finance_advisor", "seo_advisor", "content_manager",
        "product_manager", "operations_manager", "ceo_assistant",
    }
    # 每条都带必备字段
    for a in resp["agents"]:
        assert "name" in a and "description" in a
        assert "downstream_dependencies" in a
        assert "loaded_skills_count" in a
        assert "active_hints_count" in a
        assert "circuit_breaker" in a
        assert a["circuit_breaker"]["agent_id"] == a["id"]


@pytest.mark.asyncio
async def test_agents_catalog_reflects_dag_dependencies(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    async def empty_hints(_aid):
        return []

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", empty_hints)

    resp = await workflow.workflow_agents_catalog()
    by_id = {a["id"]: a for a in resp["agents"]}
    # data_analyst 的下游：finance_advisor + ceo_assistant
    assert "finance_advisor" in by_id["data_analyst"]["downstream_dependencies"]
    assert "ceo_assistant" in by_id["data_analyst"]["downstream_dependencies"]
    # ceo_assistant 没下游
    assert by_id["ceo_assistant"]["downstream_dependencies"] == []


@pytest.mark.asyncio
async def test_agents_catalog_reflects_circuit_breaker_state(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.agents import circuit_breaker
    from app.api import workflow

    async def empty_hints(_aid):
        return []

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", empty_hints)

    # 让 data_analyst 进入 OPEN
    for _ in range(4):
        circuit_breaker.record_failure("data_analyst")

    resp = await workflow.workflow_agents_catalog()
    by_id = {a["id"]: a for a in resp["agents"]}
    assert by_id["data_analyst"]["circuit_breaker"]["phase"] == "open"
    assert by_id["ceo_assistant"]["circuit_breaker"]["phase"] == "closed"


@pytest.mark.asyncio
async def test_agents_catalog_includes_active_hints_count(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    async def fake_hints(aid):
        if aid == "data_analyst":
            return ["hint A", "hint B"]
        return []

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", fake_hints)

    resp = await workflow.workflow_agents_catalog()
    by_id = {a["id"]: a for a in resp["agents"]}
    assert by_id["data_analyst"]["active_hints_count"] == 2
    assert by_id["ceo_assistant"]["active_hints_count"] == 0


@pytest.mark.asyncio
async def test_agents_catalog_handles_hints_failure_gracefully(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    async def broken_hints(_aid):
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", broken_hints)

    # 端点不应 500
    resp = await workflow.workflow_agents_catalog()
    assert resp["count"] == 7
    for a in resp["agents"]:
        assert a["active_hints_count"] == 0  # 失败 → 0


@pytest.mark.asyncio
async def test_agent_profile_returns_full_payload(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    async def fake_hints(aid):
        return ["hint 1", "hint 2"]

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", fake_hints)

    resp = await workflow.workflow_agent_profile(agent_id="data_analyst")
    assert resp["id"] == "data_analyst"
    assert resp["name"]
    assert "description" in resp
    assert "downstream_dependencies" in resp
    assert "model_config" in resp
    assert "max_tokens" in resp["model_config"]
    assert "temperature" in resp["model_config"]
    assert resp["active_prompt_hints"] == ["hint 1", "hint 2"]
    assert "skills" in resp
    assert isinstance(resp["skills"], list)
    # 每条 skill 至少带 skill_id / name / priority / description
    for s in resp["skills"]:
        assert "skill_id" in s
        assert "priority" in s
        assert "description" in s


@pytest.mark.asyncio
async def test_agent_profile_404_for_unknown_id(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_agent_profile(agent_id="nonexistent_agent")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_agent_profile_handles_skill_load_failure(monkeypatch):
    """skill loader 抛错时 profile 端点仍返 200 + skills=[]。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow

    async def empty_hints(_aid):
        return []

    def broken_skills(_aid):
        raise RuntimeError("SKILLS.md missing")

    monkeypatch.setattr("app.core.prompt_evolution.fetch_active_hints", empty_hints)
    monkeypatch.setattr("app.core.skill_loader.get_skills_for_agent", broken_skills)

    resp = await workflow.workflow_agent_profile(agent_id="ceo_assistant")
    assert resp["id"] == "ceo_assistant"
    assert resp["skills"] == []  # 容错降级
