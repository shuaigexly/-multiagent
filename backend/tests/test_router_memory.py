"""model_router + memory 单元测试。"""
import os
from unittest.mock import patch

import pytest

from app.core.memory import (
    _cosine,
    _hash_embedding,
    format_memory_hits,
    MemoryHit,
)
from app.core.model_router import ModelTier, resolve_model, select_tier


def test_select_tier_ceo_is_deep():
    assert select_tier(agent_id="ceo_assistant", prompt_len=2000) == ModelTier.DEEP


def test_select_tier_low_confidence_is_deep():
    assert select_tier(agent_id="data_analyst", confidence=2) == ModelTier.DEEP


def test_select_tier_retry_is_deep():
    assert select_tier(agent_id="data_analyst", retry_attempt=1) == ModelTier.DEEP


def test_select_tier_short_prompt_is_fast():
    assert select_tier(agent_id="data_analyst", prompt_len=400) == ModelTier.FAST


def test_select_tier_finance_short_still_standard():
    # finance 不允许走 FAST 档（金融分析需要充分上下文）
    assert select_tier(agent_id="finance_advisor", prompt_len=400) == ModelTier.STANDARD


def test_select_tier_long_prompt_is_standard():
    assert select_tier(agent_id="data_analyst", prompt_len=3000) == ModelTier.STANDARD


def test_resolve_model_falls_back_to_standard_when_tier_env_missing(monkeypatch):
    monkeypatch.delenv("LLM_FAST_MODEL", raising=False)
    monkeypatch.delenv("LLM_DEEP_MODEL", raising=False)
    fast = resolve_model(ModelTier.FAST)
    deep = resolve_model(ModelTier.DEEP)
    standard = resolve_model(ModelTier.STANDARD)
    # 缺省时三档使用同一 model
    assert fast.model == standard.model
    assert deep.model == standard.model


def test_resolve_model_uses_explicit_env(monkeypatch):
    monkeypatch.setenv("LLM_DEEP_MODEL", "deepseek-reasoner")
    monkeypatch.setenv("LLM_DEEP_BASE_URL", "https://api.deepseek.com/v1")
    cfg = resolve_model(ModelTier.DEEP)
    assert cfg.model == "deepseek-reasoner"
    assert cfg.base_url == "https://api.deepseek.com/v1"


def test_hash_embedding_deterministic():
    a = _hash_embedding("MAU 月活跃用户分析")
    b = _hash_embedding("MAU 月活跃用户分析")
    assert a == b
    assert len(a) == 128


def test_hash_embedding_similarity_close_for_related():
    a = _hash_embedding("AI 产品内容战略分析")
    b = _hash_embedding("AI 产品内容增长分析")
    c = _hash_embedding("Solar panel installation")
    sim_ab = _cosine(a, b)
    sim_ac = _cosine(a, c)
    assert sim_ab > sim_ac, f"related should be more similar: ab={sim_ab} ac={sim_ac}"


def test_format_memory_hits_empty():
    assert format_memory_hits([]) == ""


def test_format_memory_hits_renders_block():
    hits = [
        MemoryHit(
            task_text="AI 产品内容战略",
            summary="MAU 增长 12%",
            similarity=0.78,
            created_at="2026-04-25T12:00:00",
        )
    ]
    block = format_memory_hits(hits)
    assert "<long_term_memory>" in block
    assert "AI 产品内容战略" in block
    assert "MAU 增长 12%" in block
    assert "0.78" in block
