"""Prompt 自演化 + 任务依赖图 测试。"""
from unittest.mock import AsyncMock, patch

import pytest

from app.bitable_workflow.scheduler import _unmet_dependencies
from app.core.prompt_evolution import (
    PROMOTE_THRESHOLD,
    fetch_active_hints,
    format_hints_block,
    maybe_promote,
)


# ---------- prompt_evolution ----------

@pytest.mark.asyncio
async def test_maybe_promote_skips_when_score_low():
    with patch(
        "app.core.llm_client.call_llm",
        new=AsyncMock(return_value="SCORE=4\nRULE=should be more careful"),
    ):
        result = await maybe_promote(agent_id="data_analyst", reflection_text="一些反思")
    assert result is None


@pytest.mark.asyncio
async def test_maybe_promote_skips_when_rule_is_skip():
    with patch(
        "app.core.llm_client.call_llm",
        new=AsyncMock(return_value="SCORE=9\nRULE=SKIP"),
    ):
        result = await maybe_promote(agent_id="data_analyst", reflection_text="一些反思")
    assert result is None


@pytest.mark.asyncio
async def test_maybe_promote_skips_unparseable_verdict():
    with patch(
        "app.core.llm_client.call_llm",
        new=AsyncMock(return_value="something random"),
    ):
        result = await maybe_promote(agent_id="data_analyst", reflection_text="x")
    assert result is None


@pytest.mark.asyncio
async def test_maybe_promote_writes_high_score_rule(tmp_path, monkeypatch):
    from app.models.database import init_db

    monkeypatch.setattr(
        "app.core.settings.settings.database_url",
        f"sqlite+aiosqlite:///{tmp_path / 'evo.db'}",
    )
    from importlib import reload
    import app.models.database as db_mod
    reload(db_mod)
    await db_mod.init_db()

    # 替换 prompt_evolution 内引用的 SessionLocal 也为新 db
    monkeypatch.setattr("app.core.prompt_evolution.AsyncSessionLocal", db_mod.AsyncSessionLocal)
    monkeypatch.setattr("app.core.prompt_evolution.AgentPromptHint", db_mod.AgentPromptHint)

    try:
        with patch(
            "app.core.llm_client.call_llm",
            new=AsyncMock(return_value="SCORE=9\nRULE=遇到 LTV/CAC 时优先调 python_calc 而非估算"),
        ):
            new_id = await maybe_promote(
                agent_id="data_analyst",
                reflection_text="上次我估算了 LTV，应该用 python_calc",
            )

        assert new_id is not None
        hints = await fetch_active_hints("data_analyst")
        assert any("python_calc" in h for h in hints)
    finally:
        await db_mod.engine.dispose()


def test_format_hints_block_renders_numbered_list():
    block = format_hints_block(["调 fetch_url", "用 python_calc 算 LTV"])
    assert "经验内化" in block
    assert "1. 调 fetch_url" in block
    assert "2. 用 python_calc 算 LTV" in block


def test_format_hints_block_empty():
    assert format_hints_block([]) == ""


def test_promote_threshold_is_strict():
    assert PROMOTE_THRESHOLD == 8


# ---------- task dependency graph ----------

def test_unmet_deps_empty_when_no_field():
    assert _unmet_dependencies("", {}) == []
    assert _unmet_dependencies(None, {}) == []
    assert _unmet_dependencies("   ", {}) == []


def test_unmet_deps_all_completed():
    index = {"1": "已完成", "2": "已完成"}
    assert _unmet_dependencies("1, 2", index) == []


def test_unmet_deps_some_pending():
    index = {"1": "已完成", "3": "分析中"}
    unmet = _unmet_dependencies("1, 3", index)
    assert len(unmet) == 1
    assert "T3" in unmet[0]
    assert "分析中" in unmet[0]


def test_unmet_deps_unknown_task_treated_as_unmet():
    index = {"1": "已完成"}
    unmet = _unmet_dependencies("1, 99", index)
    assert any("T99" in u and "未知" in u for u in unmet)


def test_unmet_deps_handles_chinese_separators_and_t_prefix():
    index = {"1": "已完成", "2": "已完成"}
    assert _unmet_dependencies("T0001；T0002", index) == []


def test_unmet_deps_handles_newline_separator():
    index = {"5": "已完成", "9": "已完成"}
    assert _unmet_dependencies("5\n9", index) == []
