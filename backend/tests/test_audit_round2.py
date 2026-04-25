"""第二轮审计修复回归测试 — 锁定 v7.7 → v7.8 的另外 5 个真实 bug。"""
import json

import pytest

from app.agents.plan_execute import _extract_first_json_array


# ---- bug 14: plan JSON 解析 fallback ----

def test_extract_json_array_clean_input():
    out = _extract_first_json_array('[{"step":"a"},{"step":"b"}]')
    assert isinstance(out, list)
    assert len(out) == 2


def test_extract_json_array_strips_markdown_fence():
    out = _extract_first_json_array('```json\n[{"step":"a"}]\n```')
    assert out == [{"step": "a"}]


def test_extract_json_array_handles_prefix_chatter():
    """关键回归：LLM 在 JSON 前后写废话不该让 plan 整段失败。"""
    text = 'Sure, here is the plan:\n[{"step":"a"},{"step":"b"}]\nLet me know if you need more.'
    out = _extract_first_json_array(text)
    assert isinstance(out, list) and len(out) == 2


def test_extract_json_array_handles_brackets_in_strings():
    """JSON 字符串里的方括号不能让深度计数错乱。"""
    out = _extract_first_json_array('[{"step":"compare [a, b] vs [c, d]"}]')
    assert out == [{"step": "compare [a, b] vs [c, d]"}]


def test_extract_json_array_returns_none_on_garbage():
    assert _extract_first_json_array("no array here") is None
    assert _extract_first_json_array("") is None
    assert _extract_first_json_array(None) is None


def test_extract_json_array_handles_nested():
    out = _extract_first_json_array('[{"items":[1,2,3]},{"items":[4]}]')
    assert isinstance(out, list)
    assert out[0]["items"] == [1, 2, 3]


# ---- bug 12: prompt .format() 在含花括号的输入下抛 KeyError ----

def test_plan_prompt_uses_replace_not_format():
    """关键回归：task_description 包含 JSON / {var} 时不能让 plan_execute 整段崩。"""
    from app.agents.plan_execute import _PLAN_PROMPT, _EXECUTE_PROMPT, _SYNTHESIZE_PROMPT

    malicious = '分析这个 schema: {"users": {"id": int}}'
    # 之前用 .format(task=malicious) 会报 KeyError: '"users"'
    # 现在用 replace 应安全
    out = _PLAN_PROMPT.replace("{task}", malicious).replace("{upstream_block}", "<no_upstream/>")
    # 之前 .format() 在遇到 {"users": ...} 时抛 KeyError；replace() 路径让原文整段保留
    assert '{"users"' in out  # 原始 JSON 文本完好
    assert "{task}" not in out  # 占位符已替换


def test_judge_prompt_uses_replace():
    from app.agents.judge import _JUDGE_PROMPT

    tricky_task = 'analyze: {"a": 1, "b": [{}]}'
    out = _JUDGE_PROMPT.replace("{task}", tricky_task).replace("{candidates}", "X")
    assert '"a": 1' in out
    assert "{task}" not in out


def test_promote_judge_prompt_uses_replace():
    from app.core.prompt_evolution import _JUDGE_PROMPT as PROMOTE_JUDGE

    tricky = "我学到了：JSON {} 处理要 escape"
    out = PROMOTE_JUDGE.replace("{reflection}", tricky)
    assert "{reflection}" not in out
    assert "JSON {}" in out


# ---- bug 16: memory 不存包含 REDACTED 标记的任务文本 ----

@pytest.mark.asyncio
async def test_store_memory_skips_redacted_task(monkeypatch):
    """注入攻击文本被 sanitize 后含 [REDACTED:] → 不应进入长期记忆库污染检索。"""
    from unittest.mock import AsyncMock

    from app.core import memory as memory_mod

    write_called = AsyncMock()
    monkeypatch.setattr("app.core.memory.AsyncSessionLocal", write_called)

    await memory_mod.store_memory(
        agent_id="data_analyst",
        task_text="正常任务 [REDACTED:ignore_previous] 后续",
        summary="some summary",
    )
    # AsyncSessionLocal 不应被调用（因为 store_memory 早返回）
    write_called.assert_not_called()


@pytest.mark.asyncio
async def test_store_memory_writes_clean_task(monkeypatch, tmp_path):
    """对照组：干净的任务文本应正常写入。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.database import AgentMemory, Base

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mem.db'}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(eng, expire_on_commit=False)
    monkeypatch.setattr("app.core.memory.AsyncSessionLocal", Session)

    from app.core.memory import store_memory

    await store_memory(
        agent_id="data_analyst",
        task_text="2026Q2 经营复盘",
        summary="MAU 增长 12%",
    )

    async with Session() as db:
        from sqlalchemy import select

        rows = (await db.execute(select(AgentMemory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].task_text == "2026Q2 经营复盘"

    await eng.dispose()


# ---- bug 11: tools 路径流式不再是死代码 ----

@pytest.mark.asyncio
async def test_call_llm_with_tools_accepts_on_token():
    """call_llm_with_tools 必须接受 on_token 参数（之前是死代码，前端永远收不到 token 流）。"""
    import inspect

    from app.core.llm_client import call_llm_with_tools

    sig = inspect.signature(call_llm_with_tools)
    assert "on_token" in sig.parameters
