"""Async client for @larksuiteoapi/lark-mcp MCP server (JSON-RPC 2.0 over stdin/stdout)."""
import asyncio
import json
import logging
import os
import shutil
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_proc: Optional[asyncio.subprocess.Process] = None
_req_id = 0


def is_mcp_available() -> bool:
    return shutil.which("npx") is not None


async def _get_proc() -> asyncio.subprocess.Process:
    global _proc
    if _proc is not None and _proc.returncode is None:
        return _proc
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set to use lark-mcp")
    _proc = await asyncio.create_subprocess_exec(
        "npx",
        "-y",
        "@larksuiteoapi/lark-mcp",
        "mcp",
        "-a",
        app_id,
        "-s",
        app_secret,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    logger.info("lark-mcp subprocess started (pid=%s)", _proc.pid)
    await _send_raw(
        _proc,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "multiagent-lark", "version": "1.0"},
            },
        },
    )
    await _read_response(_proc)
    await _send_raw(
        _proc,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )
    return _proc


async def _send_raw(proc: asyncio.subprocess.Process, obj: dict) -> None:
    if proc.stdin is None:
        raise RuntimeError("lark-mcp stdin is not available")
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode()
    proc.stdin.write(data)
    await proc.stdin.drain()


async def _read_response(proc: asyncio.subprocess.Process) -> dict:
    if proc.stdout is None:
        raise RuntimeError("lark-mcp stdout is not available")
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
    if not line:
        raise RuntimeError("lark-mcp closed stdout unexpectedly")
    return json.loads(line.decode())


async def call_tool(tool_name: str, params: dict[str, Any]) -> Any:
    """Call a Feishu MCP tool by name. Returns the tool result."""
    global _req_id, _proc
    if not is_mcp_available():
        raise RuntimeError("npx is not available; install Node.js to use lark-mcp")
    async with _lock:
        proc = await _get_proc()
        _req_id += 1
        req_id = _req_id
        try:
            await _send_raw(
                proc,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": params},
                },
            )
            resp = await _read_response(proc)
        except Exception:
            _proc = None
            raise
    if "error" in resp:
        raise RuntimeError(f"lark-mcp tool error: {resp['error']}")
    result = resp.get("result", {})
    content = result.get("content", [])
    if content and isinstance(content, list) and content[0].get("type") == "text":
        try:
            return json.loads(content[0]["text"])
        except json.JSONDecodeError:
            return content[0]["text"]
    return result


async def list_tools() -> list[dict]:
    """List all available Feishu MCP tools."""
    global _req_id, _proc
    if not is_mcp_available():
        return []
    async with _lock:
        proc = await _get_proc()
        _req_id += 1
        req_id = _req_id
        try:
            await _send_raw(
                proc,
                {"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}},
            )
            resp = await _read_response(proc)
        except Exception:
            _proc = None
            raise
    return resp.get("result", {}).get("tools", [])


async def shutdown() -> None:
    """Gracefully terminate the MCP subprocess."""
    global _proc
    if _proc and _proc.returncode is None:
        if _proc.stdin is not None:
            _proc.stdin.write_eof()
        await asyncio.wait_for(_proc.wait(), timeout=5)
        _proc = None
        logger.info("lark-mcp subprocess stopped")
