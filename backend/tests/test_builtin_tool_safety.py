import importlib

import pytest


def _reload_builtin_tools():
    from app.agents import builtin_tools
    from app.agents.tools import reset_registry

    reset_registry()
    importlib.reload(builtin_tools)


@pytest.mark.asyncio
async def test_fetch_url_tool_rejects_private_targets():
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    result = await dispatch_tool("fetch_url", {"url": "http://127.0.0.1:8000/admin"})

    assert result.startswith("ERROR:")
    assert "unsafe url" in result


@pytest.mark.asyncio
async def test_python_calc_blocks_large_exponents():
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    result = await dispatch_tool("python_calc", {"expression": "10 ** 1000000"})

    assert result.startswith("ERROR:")
    assert "unsafe expression" in result


@pytest.mark.asyncio
async def test_python_calc_blocks_large_repetition():
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    result = await dispatch_tool("python_calc", {"expression": "'x' * 100000000"})

    assert result.startswith("ERROR:")
    assert "unsafe expression" in result


@pytest.mark.asyncio
async def test_python_calc_blocks_nested_large_repetition():
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    result = await dispatch_tool("python_calc", {"expression": "[0] * 10000 * 10000"})

    assert result.startswith("ERROR:")
    assert "unsafe expression" in result


@pytest.mark.asyncio
async def test_python_calc_blocks_dynamic_sequence_repetition():
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    result = await dispatch_tool("python_calc", {"expression": "list(range(10000)) * 1000"})

    assert result.startswith("ERROR:")
    assert "unsafe expression" in result


@pytest.mark.asyncio
async def test_python_calc_blocks_expensive_math_calls():
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    result = await dispatch_tool(
        "python_calc",
        {"expression": "math.factorial(100000000)"},
    )

    assert result.startswith("ERROR:")
    assert "unsafe expression" in result
