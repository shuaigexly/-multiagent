"""v8.6.20-r41: 单 agent 熔断器回归。

锁定契约：
1. 失败率 ≥ 0.6 + 至少 3 次调用 → OPEN
2. OPEN 期间 is_open=True
3. cooldown 后自动 HALF_OPEN（is_open=False，放行下一次试探）
4. HALF_OPEN 成功 → 关闭熔断；失败 → 重置 cooldown
5. 熔断器状态通过 get_status() 暴露
6. /telemetry 端点包含每个 agent 的熔断状态
7. _safe_analyze 在 agent OPEN 时短路走 fallback（不调 LLM）
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
def _clean_breakers():
    from app.agents import circuit_breaker
    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


def test_breaker_starts_closed():
    from app.agents import circuit_breaker
    assert circuit_breaker.is_open("data_analyst") is False
    status = circuit_breaker.get_status("data_analyst")
    assert status["phase"] == "closed"


def test_breaker_does_not_trip_below_min_calls():
    """min_calls=3：只 1-2 次失败不应熔断（冷启动避免假阳）。"""
    from app.agents import circuit_breaker
    circuit_breaker.record_failure("data_analyst")
    circuit_breaker.record_failure("data_analyst")
    assert circuit_breaker.is_open("data_analyst") is False


def test_breaker_trips_after_failure_ratio_threshold():
    from app.agents import circuit_breaker
    # 4 fail + 1 success = 80% failure ratio in 5 calls → 触发熔断（默认阈值 0.6）
    for _ in range(4):
        circuit_breaker.record_failure("data_analyst")
    circuit_breaker.record_success("data_analyst")
    assert circuit_breaker.is_open("data_analyst") is True
    status = circuit_breaker.get_status("data_analyst")
    assert status["phase"] == "open"
    assert status["failure_ratio"] >= 0.6


def test_breaker_remains_closed_when_success_dominates():
    from app.agents import circuit_breaker
    # 8 success + 2 fail = 20% failure < 60% → closed
    for _ in range(8):
        circuit_breaker.record_success("data_analyst")
    for _ in range(2):
        circuit_breaker.record_failure("data_analyst")
    assert circuit_breaker.is_open("data_analyst") is False


def test_breaker_status_includes_remaining_cooldown():
    from app.agents import circuit_breaker
    for _ in range(4):
        circuit_breaker.record_failure("seo_advisor")
    circuit_breaker.record_success("seo_advisor")
    status = circuit_breaker.get_status("seo_advisor")
    assert status["phase"] == "open"
    # 默认 cooldown=300s
    assert 0 < status["cooldown_remaining_s"] <= 300


def test_breaker_recovers_after_half_open_success(monkeypatch):
    """模拟 cooldown 过期 → half-open → success → closed。"""
    from app.agents import circuit_breaker
    import time

    aid = "finance_advisor"
    for _ in range(4):
        circuit_breaker.record_failure(aid)
    assert circuit_breaker.is_open(aid) is True

    # monkeypatch time.monotonic 让熔断器以为 cooldown 已结束
    state = circuit_breaker._states[aid]
    state.opened_at = time.monotonic() - 400  # 已过 300s cooldown

    # 下一次 is_open 应该转 half_open 并放行
    assert circuit_breaker.is_open(aid) is False
    assert state.half_open is True

    # half-open 期间一次成功 → 关闭熔断
    circuit_breaker.record_success(aid)
    assert state.opened_at == 0.0
    assert state.half_open is False
    assert circuit_breaker.is_open(aid) is False


def test_breaker_reopens_when_half_open_probe_fails():
    from app.agents import circuit_breaker
    import time

    aid = "operations_manager"
    for _ in range(4):
        circuit_breaker.record_failure(aid)
    state = circuit_breaker._states[aid]
    state.opened_at = time.monotonic() - 400  # 已过 cooldown

    # 转 half-open
    assert circuit_breaker.is_open(aid) is False
    assert state.half_open is True

    # half-open 探活又失败 → 重置 cooldown
    initial_opened_at = state.opened_at
    circuit_breaker.record_failure(aid)
    assert state.half_open is False
    assert state.opened_at > initial_opened_at  # cooldown 重置
    # 现在又是 OPEN 状态
    assert circuit_breaker.is_open(aid) is True


def test_breaker_reset_clears_individual_state():
    from app.agents import circuit_breaker
    for _ in range(4):
        circuit_breaker.record_failure("product_manager")
    assert circuit_breaker.is_open("product_manager") is True

    circuit_breaker.reset("product_manager")
    assert circuit_breaker.is_open("product_manager") is False
    assert circuit_breaker.get_status("product_manager")["phase"] == "closed"


@pytest.mark.asyncio
async def test_safe_analyze_short_circuits_when_breaker_open(monkeypatch):
    """端到端：agent 已 OPEN → _safe_analyze 直接返 fallback，不调 agent.analyze。"""
    from app.agents import circuit_breaker
    from app.agents.base_agent import AgentResult, ResultSection
    from app.bitable_workflow import workflow_agents

    # 先 trip 熔断
    aid = "data_analyst"
    for _ in range(4):
        circuit_breaker.record_failure(aid)
    assert circuit_breaker.is_open(aid) is True

    analyze_calls = []

    class TrackingAgent:
        agent_id = aid
        agent_name = "数据分析师"

        async def analyze(self, **kwargs):
            analyze_calls.append(kwargs)
            return AgentResult(
                agent_id=aid, agent_name="数据分析师",
                sections=[ResultSection(title="x", content="不该被调到")],
                action_items=[], raw_output="OK", confidence_hint=4,
            )

    async def fake_get(*_a, **_kw):
        return None

    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_cached_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_shared_result", fake_get)

    result = await workflow_agents._safe_analyze(
        TrackingAgent(),
        "test task",
        upstream=[],
        data_summary=None,
        task_id="t_cb",
        dimension="测试",
    )

    # 关键：agent.analyze 没被调用
    assert analyze_calls == []
    # 返回 fallback
    assert workflow_agents._is_fallback_result(result)
    # raw_output 应表明是 CB 触发
    assert "circuit_breaker_open" in result.raw_output


@pytest.mark.asyncio
async def test_telemetry_endpoint_exposes_circuit_breakers(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.agents import circuit_breaker
    from app.api import workflow
    from app.core import budget

    # 制造 1 个 OPEN 1 个 closed
    for _ in range(4):
        circuit_breaker.record_failure("data_analyst")
    circuit_breaker.record_success("ceo_assistant")

    monkeypatch.setattr(workflow.runner, "is_running", lambda: False)

    async def fake_status():
        return {"tenant_today": {"used": 0}, "global_today": {"used": 0}}

    monkeypatch.setattr(budget, "get_status", fake_status)

    resp = await workflow.workflow_telemetry()
    cbs = resp["circuit_breakers"]
    assert len(cbs) == 7  # 7 个岗位都被报告
    by_aid = {c["agent_id"]: c for c in cbs}
    assert by_aid["data_analyst"]["phase"] == "open"
    assert by_aid["ceo_assistant"]["phase"] == "closed"
    assert by_aid["data_analyst"]["failures_in_window"] >= 3
