"""Thin async wrapper around @larksuite/cli npm package."""
import asyncio
import json
import logging
import os
import shutil
from typing import Optional

from app.core.settings import get_feishu_app_id, get_feishu_app_secret
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)
CLI_AVAILABLE: Optional[bool] = None
_LARK_CLI_VERSION = os.getenv("LARK_CLI_VERSION", "1.1.0")


import threading as _threading
_cli_available_lock = _threading.Lock()


def is_cli_available() -> bool:
    """v8.3 修复 race — 双检守护，避免并发首次调用重复执行 shutil.which。"""
    global CLI_AVAILABLE
    if CLI_AVAILABLE is None:
        with _cli_available_lock:
            if CLI_AVAILABLE is None:
                CLI_AVAILABLE = shutil.which("npx") is not None
    return CLI_AVAILABLE


async def cli_create_doc(title: str, markdown: str, folder_token: Optional[str] = None) -> dict:
    """Create Feishu doc from markdown via lark-cli. Returns {"url": ..., "token": ...}."""
    args = [
        "npx",
        "--yes",
        f"@larksuite/cli@{_LARK_CLI_VERSION}",
        "lark-doc",
        "+create",
        "--title",
        title,
        "--content",
        markdown,
    ]
    if folder_token:
        args += ["--folder", folder_token]
    return await _run_cli(args)


async def cli_create_slides(
    title: str,
    slides_xml: list[str],
    folder_token: Optional[str] = None,
) -> dict:
    """Create Feishu slides via lark-cli XML. Returns {"url": ..., "token": ...}."""
    args = [
        "npx",
        "--yes",
        f"@larksuite/cli@{_LARK_CLI_VERSION}",
        "lark-slides",
        "+create",
        "--title",
        title,
        "--slides",
        json.dumps(slides_xml, ensure_ascii=False),
    ]
    if folder_token:
        args += ["--folder", folder_token]
    return await _run_cli(args)


async def cli_base(shortcut: str, *args: str) -> dict:
    """Run a lark-base shortcut, for example `+advperm-enable` or `+dashboard-create`."""
    cmd = [
        "npx",
        "--yes",
        f"@larksuite/cli@{_LARK_CLI_VERSION}",
        "lark-base",
        shortcut,
        *args,
    ]
    return await _run_cli(cmd)


async def _run_cli(args: list[str]) -> dict:
    env = {
        **os.environ,
        "FEISHU_APP_ID": get_feishu_app_id() or "",
        "FEISHU_APP_SECRET": get_feishu_app_secret() or "",
    }
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise RuntimeError("lark-cli timed out after 120s") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"lark-cli failed (rc={proc.returncode}): "
            f"{truncate_with_marker(stderr.decode(), 500)}"
        )
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {"raw": truncate_with_marker(stdout.decode(), 200)}
