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
import threading as _threading
_LLM_SEMAPHORE_INIT = _threading.Lock()


def _get_llm_semaphore() -> asyncio.Semaphore:
    """v8.2 修复：懒初始化 race — 并发首次 LLM 调用各自创建独立 Semaphore，
    并发限流彻底失效（实际可能 4-6 个 LLM 同时跑）→ 频繁 429。
    threading.Lock 双检守护。
    """
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        with _LLM_SEMAPHORE_INIT:
            if _LLM_SEMAPHORE is None:
                _LLM_SEMAPHORE = asyncio.Semaphore(2)
    return _LLM_SEMAPHORE


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    tier: str | None = None,
) -> str:
    """tier 可选 'fast' / 'standard' / 'deep'；缺省为 standard。"""
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

    # 选档
    from app.core.model_router import ModelTier, resolve_model

    cfg = resolve_model(tier or ModelTier.STANDARD)
    return await _call_openai_compatible(
        system_prompt,
        user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
    )


async def _call_openai_compatible(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=api_key or get_llm_api_key(),
        base_url=base_url or get_llm_base_url(),
    )
    try:
        use_model = model or get_llm_model()
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                async with _get_llm_semaphore():
                    resp = await client.chat.completions.create(
                        model=use_model,
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
                # v8.6.18：reasoning_tokens 单独记账（豆包/o1 类 reasoning model
                # 在 completion_tokens_details.reasoning_tokens 返回，之前丢失了
                # 这一维度。火山方舟单价对推理 tokens 通常和输出同价或更高）
                try:
                    usage = getattr(resp, "usage", None)
                    if usage is not None:
                        details = getattr(usage, "completion_tokens_details", None)
                        reasoning = 0
                        if details is not None:
                            reasoning = int(getattr(details, "reasoning_tokens", 0) or 0)
                        await record_usage(
                            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                            reasoning_tokens=reasoning,
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
    finally:
        try:
            await client.close()
        except Exception as exc:
            logger.debug("AsyncOpenAI close failed: %s", exc)


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
    tier: str | None = None,
) -> str:
    """Streaming LLM call with deterministic client cleanup."""
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
        logger.warning("Streaming LLM refused - budget exceeded: %s", exc)
        raise

    from openai import AsyncOpenAI

    from app.core.model_router import ModelTier, resolve_model

    cfg = resolve_model(tier or ModelTier.STANDARD)
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    chunks: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0

    try:
        async with _get_llm_semaphore():
            stream = await client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            try:
                async for event in stream:
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
            except Exception as stream_exc:
                partial = "".join(chunks).strip()
                logger.warning(
                    "call_llm_streaming interrupted after %d chars: %s",
                    len(partial),
                    stream_exc,
                )
                if not partial:
                    raise

        if prompt_tokens or completion_tokens:
            try:
                await record_usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
            except Exception as exc:
                logger.debug("record_usage failed: %s", exc)

        return "".join(chunks).strip()
    finally:
        try:
            await client.close()
        except Exception as exc:
            logger.debug("AsyncOpenAI close failed: %s", exc)


async def call_llm_with_tools(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 2000,
    max_tool_iterations: int = 4,
    tier: str | None = None,
    on_token: Any = None,
) -> str:
    """OpenAI-compatible function-calling entrypoint."""
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
    from app.core.model_router import ModelTier, resolve_model

    tools_schema = get_openai_tools_schema()
    if not tools_schema:
        return await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            tier=tier,
        )

    cfg = resolve_model(tier or ModelTier.STANDARD)
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_content = ""

    try:
        for iteration in range(max_tool_iterations):
            try:
                await check_budget(strict=True)
            except BudgetExceeded as exc:
                logger.warning("Tool loop aborted - budget exceeded at iter %s: %s", iteration, exc)
                break

            is_final_iter = iteration == max_tool_iterations - 1
            use_stream = bool(on_token) and is_final_iter

            async with _get_llm_semaphore():
                try:
                    if use_stream:
                        chunks: list[str] = []
                        final_prompt_tokens = 0
                        final_completion_tokens = 0
                        stream = await client.chat.completions.create(
                            model=cfg.model,
                            messages=messages,
                            tools=tools_schema,
                            tool_choice="none",
                            temperature=temperature,
                            max_tokens=max_tokens,
                            stream=True,
                            stream_options={"include_usage": True},
                        )
                        try:
                            async for event in stream:
                                if getattr(event, "usage", None):
                                    final_prompt_tokens = int(getattr(event.usage, "prompt_tokens", 0) or 0)
                                    final_completion_tokens = int(
                                        getattr(event.usage, "completion_tokens", 0) or 0
                                    )
                                if not event.choices:
                                    continue
                                delta = event.choices[0].delta
                                piece = getattr(delta, "content", None)
                                if not piece:
                                    continue
                                chunks.append(piece)
                                try:
                                    res = on_token(piece)
                                    if asyncio.iscoroutine(res):
                                        await res
                                except Exception as cb_exc:
                                    logger.debug("on_token callback failed: %s", cb_exc)
                        except Exception as stream_exc:
                            partial = "".join(chunks).strip()
                            logger.warning(
                                "stream interrupted at iter=%s after %d chars: %s",
                                iteration,
                                len(partial),
                                stream_exc,
                            )
                            if not partial:
                                raise
                        if final_prompt_tokens or final_completion_tokens:
                            try:
                                await record_usage(
                                    prompt_tokens=final_prompt_tokens,
                                    completion_tokens=final_completion_tokens,
                                )
                            except Exception as exc:
                                logger.debug("record_usage failed: %s", exc)
                        return "".join(chunks).strip() or last_content

                    resp = await client.chat.completions.create(
                        model=cfg.model,
                        messages=messages,
                        tools=tools_schema,
                        tool_choice="auto" if not is_final_iter else "none",
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
                if on_token and last_content:
                    try:
                        res = on_token(last_content)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as cb_exc:
                        logger.debug("on_token (final content push) failed: %s", cb_exc)
                return last_content or "(LLM returned empty content after tool loop)"

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

            async def _run_tool(tc):
                result = await dispatch_tool(tc.function.name, tc.function.arguments)
                return tc.id, tc.function.name, result

            outcomes = await asyncio.gather(
                *[_run_tool(tc) for tc in tool_calls],
                return_exceptions=True,
            )
            # v8.6.20-r9（审计 #4）：OpenAI tool-calling 协议强制 — assistant
            # message.tool_calls 中每个 tool_call_id，下一轮 messages 必须有对应
            # role=tool 响应。之前异常 outcome 时直接 continue 不 append → 下一轮
            # 请求 400 An assistant message with 'tool_calls' must be followed by
            # tool messages，工具循环就此中断。改为对失败也补 error 占位 tool 消息。
            for tc, outcome in zip(tool_calls, outcomes):
                if isinstance(outcome, Exception):
                    logger.warning("tool.failed iter=%s id=%s err=%s", iteration, tc.id, outcome)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"[tool error] {type(outcome).__name__}: {outcome}",
                    })
                    continue
                tc_id, tool_name, result = outcome
                logger.info(
                    "tool.completed iter=%s name=%s result_len=%s",
                    iteration,
                    tool_name,
                    len(result) if isinstance(result, str) else 0,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result,
                })

        return last_content or "(LLM exceeded max tool iterations without final answer)"
    finally:
        try:
            await client.close()
        except Exception as exc:
            logger.debug("AsyncOpenAI close failed: %s", exc)
