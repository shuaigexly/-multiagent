"""Agent 工具调用框架测试。"""
import pytest

from app.agents.tools import (
    dispatch_tool,
    get_openai_tools_schema,
    list_tool_names,
    register_tool,
    reset_registry,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry()
    yield
    reset_registry()


@pytest.mark.asyncio
async def test_register_and_dispatch_simple_tool():
    @register_tool(
        name="echo",
        description="Echo back input",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    async def echo(text: str) -> str:
        return f"echoed:{text}"

    assert "echo" in list_tool_names()
    result = await dispatch_tool("echo", {"text": "hi"})
    assert result == "echoed:hi"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error_not_raise():
    result = await dispatch_tool("does-not-exist", {})
    assert result.startswith("ERROR:")
    assert "not found" in result


@pytest.mark.asyncio
async def test_dispatch_invalid_args_returns_error():
    @register_tool(
        name="add",
        description="Add",
        parameters={"type": "object", "properties": {"a": {"type": "number"}}, "required": ["a"]},
    )
    async def add(a: int) -> int:
        return a + 1

    result = await dispatch_tool("add", "not-json")
    assert result.startswith("ERROR:")


@pytest.mark.asyncio
async def test_dispatch_handler_exception_caught():
    @register_tool(
        name="boom",
        description="Always raises",
        parameters={"type": "object", "properties": {}},
    )
    async def boom() -> str:
        raise RuntimeError("intentional")

    result = await dispatch_tool("boom", {})
    assert result.startswith("ERROR:")
    assert "intentional" in result


@pytest.mark.asyncio
async def test_openai_schema_format():
    @register_tool(
        name="t1",
        description="d1",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}},
    )
    async def t1(x: str) -> str:
        return x

    schema = get_openai_tools_schema()
    assert len(schema) == 1
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "t1"
    assert schema[0]["function"]["description"] == "d1"
    assert schema[0]["function"]["parameters"]["properties"]["x"]["type"] == "string"


def _reload_builtin_tools():
    """reset_registry 把模块级 _REGISTRY 清空了，需重新执行 builtin_tools 注册。"""
    import importlib

    from app.agents import builtin_tools

    importlib.reload(builtin_tools)


@pytest.mark.asyncio
async def test_python_calc_blocks_dangerous_tokens():
    _reload_builtin_tools()
    result = await dispatch_tool("python_calc", {"expression": "import os"})
    assert result.startswith("ERROR:")
    assert "forbidden" in result


@pytest.mark.asyncio
async def test_python_calc_safe_math():
    _reload_builtin_tools()
    result = await dispatch_tool("python_calc", {"expression": "math.sqrt(16) + sum([1,2,3])"})
    # math.sqrt(16) = 4.0; sum = 6 → 10.0
    assert result == "10.0"


@pytest.mark.asyncio
async def test_fetch_url_rejects_non_http():
    _reload_builtin_tools()
    result = await dispatch_tool("fetch_url", {"url": "ftp://evil.invalid/"})
    assert result.startswith("ERROR:")
