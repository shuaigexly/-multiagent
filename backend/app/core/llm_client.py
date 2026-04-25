"""LLM call factory for OpenAI-compatible and Feishu Aily providers."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

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


async def call_llm_streaming(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    on_token: Any = None,
) -> str:
    """流式 LLM 调用：每个 token 通过 on_token(chunk:str) 增量回调，最终返回完整内容。

    on_token 可以是 sync 或 async 函数；返回值忽略。
    用于把 LLM 思考实时推送到 SSE 频道，让前端"看到 agent 思考"。
    feishu_aily 不支持流式 → 回退普通调用并触发一次性回调。
    """
    provider = get_llm_provider().strip().lower()
    if provider == "feishu_aily":
        text = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if on_token:
            res = on_token(text)
            if asyncio.iscoroutine(res):
                await res
        return text

    try:
        await check_budget(strict=True)
    except BudgetExceeded as exc:
        logger.warning("Streaming LLM refused — budget exceeded: %s", exc)
        raise

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=get_llm_api_key(), base_url=get_llm_base_url())
    chunks: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    async with _get_llm_semaphore():
        stream = await client.chat.completions.create(
            model=get_llm_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for event in stream:
            # usage 仅在最后一个 chunk 上出现（include_usage=True）
            if getattr(event, "usage", None):
                prompt_tokens = int(getattr(event.usage, "prompt_tokens", 0) or 0)
                completion_tokens = int(getattr(event.usage, "completion_tokens", 0) or 0)
            if not event.choices:
                continue
            delta = event.choices[0].delta
            piece = getattr(delta, "content", None)
            if not piece:
                continue
            chunks.append(piece)
            if on_token:
                try:
                    res = on_token(piece)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as cb_exc:
                    logger.debug("on_token callback failed: %s", cb_exc)

    if prompt_tokens or completion_tokens:
        try:
            await record_usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        except Exception as exc:
            logger.debug("record_usage failed: %s", exc)

    return "".join(chunks).strip()


async def call_llm_with_tools(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    max_tool_iterations: int = 4,
) -> str:
    """带工具调用的 LLM 入口（OpenAI function calling 兼容协议）。

    Agent 在分析过程中可决定调用 fetch_url / bitable_query / feishu_sheet / python_calc。
    每个 iteration 检查 budget；超出预算或达到 max_tool_iterations 即停止工具循环
    并强制 LLM 用现有信息给出最终答案。

    feishu_aily provider 不支持 function calling，回退到普通 call_llm。
    """
    provider = get_llm_provider().strip().lower()
    if provider == "feishu_aily":
        return await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    from openai import AsyncOpenAI
    from app.agents.tools import dispatch_tool, get_openai_tools_schema

    tools_schema = get_openai_tools_schema()
    if not tools_schema:
        # 没有任何工具注册 → 退回普通调用
        return await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    client = AsyncOpenAI(api_key=get_llm_api_key(), base_url=get_llm_base_url())
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    last_content: str = ""
    for iteration in range(max_tool_iterations):
        try:
            await check_budget(strict=True)
        except BudgetExceeded as exc:
            logger.warning("Tool loop aborted — budget exceeded at iter %s: %s", iteration, exc)
            break

        async with _get_llm_semaphore():
            try:
                resp = await client.chat.completions.create(
                    model=get_llm_model(),
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto" if iteration < max_tool_iterations - 1 else "none",
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                logger.warning("call_llm_with_tools iter=%s failed: %s", iteration, exc)
                if iteration == 0:
                    raise
                break

        usage = getattr(resp, "usage", None)
        if usage is not None:
            try:
                await record_usage(
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
            except Exception as exc:
                logger.debug("record_usage failed: %s", exc)

        msg = resp.choices[0].message
        last_content = (msg.content or "").strip()
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            return last_content or "(LLM returned empty content after tool loop)"

        # 把 assistant 的 tool_calls 加入对话历史
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        # 并行执行所有 tool calls
        async def _run(tc):
            result = await dispatch_tool(tc.function.name, tc.function.arguments)
            return tc.id, tc.function.name, result

        outcomes = await asyncio.gather(*[_run(tc) for tc in tool_calls])
        for tc_id, tool_name, result in outcomes:
            logger.info(
                "tool.completed iter=%s name=%s result_len=%s",
                iteration, tool_name, len(result) if isinstance(result, str) else 0,
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })

    # 达到 max_tool_iterations 还没收敛 → 用最后一次 content 兜底
    return last_content or "(LLM exceeded max tool iterations without final answer)"
