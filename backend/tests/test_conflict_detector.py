"""v8.6.20-r33: cross-agent 健康度冲突检测器单测 + CEO prompt 注入集成测试。

锁定的契约：
1. detect_health_conflicts 只在 colour gap ≥ 2 且双方 confidence ≥ 3 时算 HARD 冲突
2. ⚪（数据不足）和 missing health_hint 不参与冲突
3. format_conflicts_for_prompt 输出可注入 CEO prompt 的 XML 块
4. 仅 CEO 助理 prompt 才会被注入 <conflict_alerts>，其他岗位不会
"""
from __future__ import annotations

import pytest

from app.agents.base_agent import AgentResult, ResultSection
from app.agents.conflict_detector import (
    HealthConflict,
    _extract_health_color,
    detect_health_conflicts,
    format_conflicts_for_prompt,
)


def _stub_result(agent_id: str, agent_name: str, *, health: str = "", confidence: int = 0) -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_name=agent_name,
        sections=[ResultSection(title="结论", content=f"{agent_name} 输出")],
        action_items=["a1"],
        raw_output="OK: stub",
        health_hint=health,
        confidence_hint=confidence,
    )


def test_extract_health_color_handles_emoji_with_label():
    assert _extract_health_color("🟢 健康") == "🟢"
    assert _extract_health_color("🔴 风险") == "🔴"
    assert _extract_health_color("⚪ 数据不足") == "⚪"


def test_extract_health_color_returns_empty_for_unrecognized():
    assert _extract_health_color("") == ""
    assert _extract_health_color("健康") == ""  # 没有 emoji 前缀
    assert _extract_health_color("✅") == ""    # 不在白名单


def test_detect_no_conflicts_when_all_agents_agree():
    upstream = [
        _stub_result("data_analyst", "数据分析师", health="🟢", confidence=4),
        _stub_result("finance_advisor", "财务顾问", health="🟢", confidence=4),
    ]
    assert detect_health_conflicts(upstream) == []


def test_detect_hard_conflict_green_vs_red():
    upstream = [
        _stub_result("data_analyst", "数据分析师", health="🟢", confidence=4),
        _stub_result("finance_advisor", "财务顾问", health="🔴", confidence=4),
    ]
    conflicts = detect_health_conflicts(upstream)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.severity_gap == 2
    assert {c.agent_a_id, c.agent_b_id} == {"data_analyst", "finance_advisor"}


def test_soft_conflict_green_vs_yellow_is_filtered_at_default_gap():
    upstream = [
        _stub_result("data_analyst", "数据分析师", health="🟢", confidence=4),
        _stub_result("finance_advisor", "财务顾问", health="🟡", confidence=4),
    ]
    # default min_gap=2 → 1 档差不出
    assert detect_health_conflicts(upstream) == []
    # 显式 min_gap=1 应该出
    soft = detect_health_conflicts(upstream, min_gap=1)
    assert len(soft) == 1


def test_low_confidence_evaluations_excluded_from_conflicts():
    upstream = [
        _stub_result("data_analyst", "数据分析师", health="🟢", confidence=2),  # too low
        _stub_result("finance_advisor", "财务顾问", health="🔴", confidence=5),
    ]
    # 数据分析师 confidence=2 < 3 → 不参与
    assert detect_health_conflicts(upstream) == []


def test_data_gap_white_health_excluded():
    upstream = [
        _stub_result("data_analyst", "数据分析师", health="⚪ 数据不足", confidence=4),
        _stub_result("finance_advisor", "财务顾问", health="🔴", confidence=4),
    ]
    # ⚪ 不算明确表态，不参与硬冲突计算
    assert detect_health_conflicts(upstream) == []


def test_conflicts_sorted_by_severity_descending():
    upstream = [
        _stub_result("a", "AgentA", health="🟢", confidence=4),
        _stub_result("b", "AgentB", health="🟡", confidence=4),
        _stub_result("c", "AgentC", health="🔴", confidence=4),
    ]
    # min_gap=1 → A-B(1) / A-C(2) / B-C(1)
    conflicts = detect_health_conflicts(upstream, min_gap=1)
    assert len(conflicts) == 3
    # 最大 gap 排最前
    assert conflicts[0].severity_gap == 2
    assert {conflicts[0].agent_a_id, conflicts[0].agent_b_id} == {"a", "c"}


def test_format_conflicts_for_prompt_returns_empty_when_none():
    assert format_conflicts_for_prompt([]) == ""


def test_format_conflicts_for_prompt_emits_alert_block():
    conflict = HealthConflict(
        agent_a_id="data_analyst",
        agent_a_name="数据分析师",
        color_a="🟢",
        confidence_a=5,
        agent_b_id="finance_advisor",
        agent_b_name="财务顾问",
        color_b="🔴",
        confidence_b=4,
    )
    block = format_conflicts_for_prompt([conflict])
    assert "<conflict_alerts>" in block
    assert "</conflict_alerts>" in block
    assert "数据分析师" in block
    assert "🟢" in block and "🔴" in block
    assert "需拍板的决策" in block  # 明确指令 CEO 在哪栏处理


@pytest.mark.asyncio
async def test_ceo_prompt_includes_conflict_alerts_when_hard_conflict_exists(monkeypatch):
    """集成验收：CEO _build_prompt 在硬冲突存在时必须把 <conflict_alerts> 注入；
    其他岗位即便 upstream 有冲突也不注入（只 CEO 拍板需要看）。"""
    from app.agents.ceo_assistant import ceo_assistant_agent
    from app.agents.data_analyst import data_analyst_agent

    upstream = [
        _stub_result("seo_advisor", "SEO 顾问", health="🟢", confidence=4),
        _stub_result("operations_manager", "运营负责人", health="🔴", confidence=4),
    ]

    # CEO prompt 必须包含 <conflict_alerts>
    ceo_prompt = await ceo_assistant_agent._build_prompt(
        task_description="Q3 经营复盘",
        data_summary=None,
        upstream_results=upstream,
        feishu_context=None,
        user_instructions=None,
    )
    assert "<conflict_alerts>" in ceo_prompt
    assert "SEO 顾问" in ceo_prompt and "运营负责人" in ceo_prompt

    # data_analyst 同样的 upstream 不应被注入（不是综合岗）
    da_prompt = await data_analyst_agent._build_prompt(
        task_description="Q3 经营复盘",
        data_summary=None,
        upstream_results=upstream,
        feishu_context=None,
        user_instructions=None,
    )
    assert "<conflict_alerts>" not in da_prompt


@pytest.mark.asyncio
async def test_ceo_prompt_skips_conflict_block_when_no_hard_conflict():
    """无硬冲突时 CEO prompt 不应被多余的空块污染。"""
    from app.agents.ceo_assistant import ceo_assistant_agent

    upstream = [
        _stub_result("seo_advisor", "SEO 顾问", health="🟢", confidence=4),
        _stub_result("operations_manager", "运营负责人", health="🟢", confidence=4),
    ]
    prompt = await ceo_assistant_agent._build_prompt(
        task_description="Q3 经营复盘",
        data_summary=None,
        upstream_results=upstream,
        feishu_context=None,
        user_instructions=None,
    )
    assert "<conflict_alerts>" not in prompt
