import importlib

import httpx
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


@pytest.mark.asyncio
async def test_tool_error_messages_redact_sensitive_values(monkeypatch):
    from app.agents import builtin_tools
    from app.agents.tools import dispatch_tool

    _reload_builtin_tools()

    async def fake_fetch_public_url_bytes(*_args, **_kwargs):
        raise httpx.RequestError(
            "Authorization: Bearer bearer-secret access_token=access-secret",
            request=httpx.Request("GET", "https://example.test/report?token=query-secret"),
        )

    monkeypatch.setattr(builtin_tools, "fetch_public_url_bytes", fake_fetch_public_url_bytes)
    fetch_result = await dispatch_tool("fetch_url", {"url": "https://example.test/report?token=query-secret"})

    async def fake_list_records(*_args, **_kwargs):
        raise RuntimeError(
            "access_token=access-secret https://open.feishu.test/open-apis/bitable/v1/apps/base-secret/tables/tbl"
        )

    monkeypatch.setattr("app.bitable_workflow.bitable_ops.list_records", fake_list_records)
    bitable_result = await dispatch_tool("bitable_query", {"app_token": "app", "table_id": "tbl"})

    async def fake_get_tenant_access_token():
        raise RuntimeError("refresh_token=refresh-secret Authorization: Bearer bearer-secret")

    monkeypatch.setattr("app.feishu.aily.get_tenant_access_token", fake_get_tenant_access_token)
    sheet_result = await dispatch_tool(
        "feishu_sheet",
        {"url": "https://tenant.feishu.test/sheets/sht123?sheet=gid123"},
    )

    combined = "\n".join([fetch_result, bitable_result, sheet_result])
    assert "access-secret" not in combined
    assert "bearer-secret" not in combined
    assert "refresh-secret" not in combined
    assert "query-secret" not in combined
    assert "base-secret" not in combined
    assert "[REDACTED]" in combined
