"""Thin async wrapper around @larksuite/cli npm package."""
import asyncio
import json
import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger(__name__)
CLI_AVAILABLE: Optional[bool] = None


def is_cli_available() -> bool:
    global CLI_AVAILABLE
    if CLI_AVAILABLE is None:
        CLI_AVAILABLE = shutil.which("npx") is not None
    return CLI_AVAILABLE


async def cli_create_doc(title: str, markdown: str, folder_token: Optional[str] = None) -> dict:
    """Create Feishu doc from markdown via lark-cli. Returns {"url": ..., "token": ...}."""
    args = [
        "npx",
        "--yes",
        "@larksuite/cli@latest",
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
        "@larksuite/cli@latest",
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


async def _run_cli(args: list[str]) -> dict:
    env = {
        **os.environ,
        "FEISHU_APP_ID": os.getenv("FEISHU_APP_ID", ""),
        "FEISHU_APP_SECRET": os.getenv("FEISHU_APP_SECRET", ""),
    }
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"lark-cli failed (rc={proc.returncode}): {stderr.decode()[:500]}")
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {"raw": stdout.decode()[:200]}
