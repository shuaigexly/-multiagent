"""LLM call factory for OpenAI-compatible and Feishu Aily providers."""
from __future__ import annotations

import asyncio
import logging

from app.core.budget import BudgetExceeded, check_budget, record_usage
from app.core.settings import (
    get_llm_api_key,
    get_llm_base_url,
    get_llm_model,
    get_llm_provider,
)

logger = logging.getLogger(__name__)

_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(2)
    return _LLM_SEMAPHORE


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> str:
    # Budget 闸门：超额前直接拦截，避免空跑 LLM 请求再记账
    try:
        await check_budget(strict=True)
    except BudgetExceeded as exc:
        logger.warning("LLM call refused — budget exceeded: %s", exc)
        raise

    provider = get_llm_provider().strip().lower()
    if provider == "feishu_aily":
        async with _get_llm_semaphore():
            return await _call_feishu_aily(system_prompt, user_prompt)

    if provider != "openai_compatible":
        logger.warning("Unknown LLM_PROVIDER=%r, falling back to openai_compatible", provider)
    return await _call_openai_compatible(
        system_prompt,
        user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def _call_openai_compatible(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=get_llm_api_key(),
        base_url=get_llm_base_url(),
    )
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with _get_llm_semaphore():
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
            # 记账：把本次调用 token 消耗写入 budget tracker
            try:
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    await record_usage(
                        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                    )
            except Exception as record_exc:
                logger.debug("Budget record_usage failed (non-fatal): %s", record_exc)
            return content
        except Exception as exc:
            last_err = exc
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(
                    "LLM call attempt %s failed: %s. Retrying in %ss...",
                    attempt + 1,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
    raise RuntimeError(f"LLM call failed after 3 attempts: {last_err}") from last_err


async def _call_feishu_aily(system_prompt: str, user_prompt: str) -> str:
    from app.feishu.aily import call_aily

    combined = f"{system_prompt}\n\n---\n\n{user_prompt}"
    return await call_aily(combined)
