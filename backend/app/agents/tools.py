"""Agent 工具调用框架（OpenAI function calling 兼容）。

注册的工具会自动暴露给 LLM；LLM 在分析过程中可决定调用哪些工具来获取
真实数据（Web / 飞书表格 / 多维表格 / 计算），而不是凭空估算。

使用：
    @register_tool(
        name="fetch_url",
        description="...",
        parameters={"type": "object", "properties": {...}, "required": [...]}
    )
    async def fetch_url(url: str) -> str:
        ...

LLM 调用流程在 llm_client.call_llm_with_tools 中实现。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]


_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """装饰器：把 async 函数注册为可被 LLM 调用的工具。"""
    def _wrap(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            handler=fn,
        )
        return fn
    return _wrap


def get_openai_tools_schema() -> list[dict[str, Any]]:
    """以 OpenAI function calling schema 输出全部已注册工具。"""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in _REGISTRY.values()
    ]


def list_tool_names() -> list[str]:
    return list(_REGISTRY.keys())


async def dispatch_tool(name: str, raw_args: str | dict[str, Any]) -> str:
    """执行工具调用，返回字符串化结果（截断 5000 字以控制 token 消耗）。

    出错时不抛异常 —— 把错误以 `ERROR: ...` 文本形式返回给 LLM，让模型决定如何降级。
    """
    spec = _REGISTRY.get(name)
    if spec is None:
        return f"ERROR: tool '{name}' not found. Available: {', '.join(_REGISTRY.keys())}"

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError as exc:
            return f"ERROR: tool args not valid JSON: {exc}"
    else:
        args = dict(raw_args or {})

    try:
        logger.info("tool.invoke", extra={"tool": name, "args_keys": list(args.keys())})
        result = await spec.handler(**args)
    except TypeError as exc:
        return f"ERROR: invalid arguments for tool '{name}': {exc}"
    except Exception as exc:
        logger.warning("tool.failed name=%s err=%s", name, exc)
        return f"ERROR: tool '{name}' raised: {exc}"

    if isinstance(result, (dict, list)):
        try:
            text = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            text = str(result)
    else:
        text = str(result)
    return text[:5000]


def reset_registry() -> None:
    """测试用 — 清空注册表。"""
    _REGISTRY.clear()
