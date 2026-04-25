"""peer_qa + chart_renderer 单元测试。"""
from unittest.mock import patch

import pytest

from app.agents.base_agent import AgentResult, ResultSection
from app.agents.peer_qa import (
    clear_peer_pool,
    get_peer_summary,
    set_peer_pool,
)
from app.agents.tools import dispatch_tool, reset_registry
from app.bitable_workflow.chart_renderer import render_chart_to_png


def _mk_result(agent_id: str, agent_name: str, content: str = "数据A") -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_name=agent_name,
        sections=[ResultSection(title="发现", content=content)],
        action_items=["行动1"],
        raw_output=content,
    )


@pytest.fixture(autouse=True)
def _refresh_registry():
    reset_registry()
    import importlib

    from app.agents import peer_qa  # noqa: F401

    importlib.reload(peer_qa)
    yield
    reset_registry()


@pytest.mark.asyncio
async def test_peer_pool_set_and_clear():
    r1 = _mk_result("data_analyst", "数据分析师")
    token = set_peer_pool([r1])
    assert "数据分析师" in get_peer_summary()
    clear_peer_pool(token)
    assert "无可追问" in get_peer_summary()


@pytest.mark.asyncio
async def test_ask_peer_unknown_agent_returns_error():
    token = set_peer_pool([_mk_result("data_analyst", "数据分析师")])
    try:
        result = await dispatch_tool(
            "ask_peer",
            {"agent_id": "ceo_assistant", "question": "x"},
        )
        # ceo_assistant 不在 pool（只有 data_analyst）→ ERROR
        assert result.startswith("ERROR:")
        assert "not in current pool" in result
    finally:
        clear_peer_pool(token)


@pytest.mark.asyncio
async def test_ask_peer_calls_llm_with_peer_context():
    peer = _mk_result("data_analyst", "数据分析师", content="MAU 10万；DAU 4万")
    token = set_peer_pool([peer])
    try:
        with patch("app.core.llm_client.call_llm", return_value="留存率 30%") as mock_llm:
            result = await dispatch_tool(
                "ask_peer",
                {"agent_id": "data_analyst", "question": "留存率多少？"},
            )
        assert result == "留存率 30%"
        # 验证 system_prompt 含同侪角色名
        kwargs = mock_llm.call_args.kwargs
        assert "数据分析师" in kwargs["system_prompt"]
        assert "MAU 10万" in kwargs["user_prompt"]
    finally:
        clear_peer_pool(token)


def test_render_chart_returns_none_on_empty_input():
    assert render_chart_to_png([]) is None
    assert render_chart_to_png(None) is None  # type: ignore[arg-type]
    assert render_chart_to_png([{"name": "x"}]) is None  # 单点不画


def test_render_chart_produces_png_bytes_when_matplotlib_available():
    chart_data = [
        {"name": "MAU", "value": 10, "unit": "万"},
        {"name": "DAU", "value": 4, "unit": "万"},
        {"name": "留存", "value": 30, "unit": "%"},
    ]
    png = render_chart_to_png(chart_data, title="测试")
    if png is None:
        pytest.skip("matplotlib not installed")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header
    assert len(png) > 500
