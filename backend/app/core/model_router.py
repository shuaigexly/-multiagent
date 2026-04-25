"""多模型路由 — 按任务复杂度选择 fast / standard / deep 三档模型。

设计：
  - FAST：低成本快速档（GLM-4-flash），用于 reflection / 工具循环 / 简单 agent
  - STANDARD：默认档（settings.llm_model），主要分析路径
  - DEEP：深度推理档（GLM-4-plus / deepseek-r1 / qwen-max），用于：
      * agent 自评 confidence < 3 的重试
      * Wave3 CEO 综合（关系到决策质量）
      * 显式标记的硬核分析

环境变量：
  LLM_FAST_MODEL / LLM_FAST_BASE_URL / LLM_FAST_API_KEY  → FAST 档（缺省回退 STANDARD）
  LLM_DEEP_MODEL / LLM_DEEP_BASE_URL / LLM_DEEP_API_KEY  → DEEP 档（缺省回退 STANDARD）
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

from app.core.settings import get_llm_api_key, get_llm_base_url, get_llm_model

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass
class ModelConfig:
    tier: ModelTier
    api_key: str
    base_url: str
    model: str


def _env_or_default(env_name: str, default: str) -> str:
    return os.getenv(env_name, "").strip() or default


def resolve_model(tier: ModelTier | str) -> ModelConfig:
    """解析某档模型实际使用的 provider/key/url/model。

    任一档配置缺失 → 回退到 STANDARD（不报错，由调用方决定是否记日志）。
    """
    if isinstance(tier, str):
        try:
            tier = ModelTier(tier)
        except ValueError:
            tier = ModelTier.STANDARD

    std_key = get_llm_api_key()
    std_base = get_llm_base_url()
    std_model = get_llm_model()

    if tier == ModelTier.STANDARD:
        return ModelConfig(tier, std_key, std_base, std_model)

    if tier == ModelTier.FAST:
        model = _env_or_default("LLM_FAST_MODEL", std_model)
        base = _env_or_default("LLM_FAST_BASE_URL", std_base)
        key = _env_or_default("LLM_FAST_API_KEY", std_key)
        return ModelConfig(ModelTier.FAST, key, base, model)

    # DEEP
    model = _env_or_default("LLM_DEEP_MODEL", std_model)
    base = _env_or_default("LLM_DEEP_BASE_URL", std_base)
    key = _env_or_default("LLM_DEEP_API_KEY", std_key)
    return ModelConfig(ModelTier.DEEP, key, base, model)


def select_tier(
    *,
    agent_id: str = "",
    prompt_len: int = 0,
    retry_attempt: int = 0,
    confidence: int = 5,
    is_summarizer: bool = False,
) -> ModelTier:
    """根据上下文启发式选档。

    - confidence < 3 或 retry_attempt > 0 → DEEP（质量重试）
    - is_summarizer 或 agent_id == 'ceo_assistant' → DEEP（决策质量）
    - prompt_len < 800 且非 ceo → FAST
    - 其他 → STANDARD
    """
    if retry_attempt > 0 or confidence < 3:
        return ModelTier.DEEP
    if is_summarizer or agent_id == "ceo_assistant":
        return ModelTier.DEEP
    if prompt_len > 0 and prompt_len < 800 and agent_id not in {"finance_advisor"}:
        return ModelTier.FAST
    return ModelTier.STANDARD
