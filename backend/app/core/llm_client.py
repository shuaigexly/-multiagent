"""
LLM 调用工厂。
根据 LLM_PROVIDER 环境变量路由到不同实现：
  openai_compatible  → 任何兼容 OpenAI /chat/completions 的服务商（默认）
  feishu_aily        → 飞书 Aily 智能伙伴（需企业开通飞书 AI）
"""
from __future__ import annotations

import asyncio
import logging

from app.core.settings import (
    get_llm_api_key,
    get_llm_base_url,
    get_llm_model,
    get_llm_provider,
)

logger = logging.getLogger(__name__)

# Limit concurrent LLM calls to avoid rate-limiting (e.g. GLM-4-flash: ~5 RPM free tier)
_LLM_SEMAPHORE = asyncio.Semaphore(2)


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    """
    统一 LLM 调用入口。

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户消息（包含任务内容）
        temperature: 生成温度（0-2），feishu_aily 模式下忽略此参数
        max_tokens: 最大输出 token 数，feishu_aily 模式下忽略此参数

    Returns:
        模型返回的文本

    Raises:
        RuntimeError: 配置错误或调用失败
    """
    provider = get_llm_provider().strip().lower()

    async with _LLM_SEMAPHORE:
        if provider == "feishu_aily":
            return await _call_feishu_aily(system_prompt, user_prompt)
        else:
            if provider != "openai_compatible":
                logger.warning(
                    "未知 LLM_PROVIDER=%r，降级使用 openai_compatible 模式", provider
                )
            return await _call_openai_compatible(
                system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens
            )


async def _call_openai_compatible(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """调用任何兼容 OpenAI Chat Completions 接口的服务商。

    支持：OpenAI、DeepSeek、火山方舟/豆包、通义千问、智谱 GLM、百川、MiniMax、Ollama 等。
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=get_llm_api_key(),
        base_url=get_llm_base_url(),
    )
    last_err = None
    for attempt in range(3):
        try:
            resp = await client.chat.completions.create(
                model=get_llm_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("LLM returned empty content")
            return content
        except Exception as e:
            last_err = e
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(
                    f"LLM call attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)
    raise RuntimeError(f"LLM call failed after 3 attempts: {last_err}") from last_err


async def _call_feishu_aily(system_prompt: str, user_prompt: str) -> str:
    """调用飞书 Aily AI 智能伙伴。

    Aily 是单轮会话制，不支持 system/user 分离，两者合并后发送。
    需设置 AILY_APP_ID 环境变量。
    """
    from app.feishu.aily import call_aily

    combined = f"{system_prompt}\n\n---\n\n{user_prompt}"
    return await call_aily(combined)
