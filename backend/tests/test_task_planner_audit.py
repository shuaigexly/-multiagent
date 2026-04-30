import json

import pytest

from app.core.task_planner import MAX_REASONING_CHARS, _llm_plan


@pytest.mark.asyncio
async def test_llm_plan_dedupes_and_bounds_selected_modules(monkeypatch):
    async def fake_call_llm(**kwargs):
        return json.dumps({
            "task_type": "general",
            "task_type_label": "综合分析",
            "selected_modules": [
                "data_analyst",
                "finance_advisor",
                "data_analyst",
                "unknown_agent",
                "seo_advisor",
                "content_manager",
                "ceo_assistant",
            ],
            "reasoning": "x" * (MAX_REASONING_CHARS + 20),
        })

    monkeypatch.setattr("app.core.llm_client.call_llm", fake_call_llm)

    plan = await _llm_plan("分析一个复杂业务问题")

    assert plan.selected_modules == [
        "data_analyst",
        "finance_advisor",
        "seo_advisor",
        "content_manager",
    ]
    assert len(plan.reasoning) == MAX_REASONING_CHARS


@pytest.mark.asyncio
async def test_llm_plan_falls_back_when_module_payload_is_not_list(monkeypatch):
    async def fake_call_llm(**kwargs):
        return json.dumps({
            "task_type": "content_growth",
            "task_type_label": "内容增长",
            "selected_modules": "data_analyst",
            "reasoning": None,
        })

    monkeypatch.setattr("app.core.llm_client.call_llm", fake_call_llm)

    plan = await _llm_plan("规划内容增长")

    assert plan.selected_modules == ["seo_advisor", "content_manager", "operations_manager"]
    assert plan.reasoning == ""
