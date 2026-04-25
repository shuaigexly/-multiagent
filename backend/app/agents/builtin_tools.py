"""内置工具 — 在应用启动时通过装饰器自动注册到 tools._REGISTRY。

工具使用原则：
  1. 只读为主，不主动改写飞书数据
  2. 网络请求严格超时（< 15s）+ 内容截断
  3. 任何出错都不能抛异常给 LLM —— 返回 'ERROR: ...' 文本，由模型决定降级
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import re
from typing import Any

import httpx

from app.agents.tools import register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool 1: fetch_url — 抓取网页文本（HTML 简单去标签）
# ---------------------------------------------------------------------------
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


@register_tool(
    name="fetch_url",
    description=(
        "抓取一个 URL 的网页文本内容（自动去除 HTML 标签）。"
        "用于查阅外部资料、行业基准、公开数据。"
        "返回前 8000 字（超长截断）。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整 http/https URL"},
        },
        "required": ["url"],
    },
)
async def fetch_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "ERROR: url must start with http:// or https://"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "FeishuAIBot/1.0"})
            resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        body = resp.text
        if "html" in ctype.lower():
            body = _strip_html(body)
        return body[:8000]
    except httpx.HTTPError as exc:
        return f"ERROR: fetch failed: {exc}"


# ---------------------------------------------------------------------------
# Tool 2: bitable_query — 查询多维表格记录
# ---------------------------------------------------------------------------
@register_tool(
    name="bitable_query",
    description=(
        "查询飞书多维表格中的记录。可按字段过滤。"
        "示例 filter: CurrentValue.[状态]=\"已完成\"。"
        "返回前 max_records 条记录的 JSON 数组。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "app_token": {"type": "string", "description": "Bitable app token（多维表格 ID）"},
            "table_id": {"type": "string", "description": "表格 ID"},
            "filter": {"type": "string", "description": "可选 filter 表达式"},
            "max_records": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
        },
        "required": ["app_token", "table_id"],
    },
)
async def bitable_query(app_token: str, table_id: str, filter: str = "", max_records: int = 10) -> Any:
    from app.bitable_workflow import bitable_ops

    try:
        rows = await bitable_ops.list_records(
            app_token,
            table_id,
            filter_expr=filter or None,
            max_records=max(1, min(int(max_records), 50)),
        )
    except Exception as exc:
        return f"ERROR: bitable query failed: {exc}"

    # 简化输出：只保留 record_id + fields
    return [
        {"record_id": r.get("record_id"), "fields": r.get("fields") or {}}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Tool 3: feishu_sheet — 读取飞书电子表格
# ---------------------------------------------------------------------------
_SHEET_TOKEN_RE = re.compile(r"/sheets/([A-Za-z0-9]+)")
_SHEET_ID_RE = re.compile(r"sheet=([A-Za-z0-9]+)")


def _parse_sheet_url(url: str) -> tuple[str | None, str | None]:
    """从飞书 sheet URL 提取 spreadsheet_token 和 sheet_id。

    形如 https://feishu.cn/sheets/abc?sheet=xyz 或 sheets/abc#sheet=xyz
    """
    token_match = _SHEET_TOKEN_RE.search(url)
    sheet_match = _SHEET_ID_RE.search(url) or re.search(r"#?sheet=([A-Za-z0-9]+)", url)
    return (
        token_match.group(1) if token_match else None,
        sheet_match.group(1) if sheet_match else None,
    )


@register_tool(
    name="feishu_sheet",
    description=(
        "读取飞书电子表格的真实数据。粘贴 sheet 完整 URL，返回前 100 行 CSV。"
        "用于基于真实业务数据分析（替代凭空估算）。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "飞书电子表格完整 URL"},
            "max_rows": {"type": "integer", "default": 100, "minimum": 1, "maximum": 500},
        },
        "required": ["url"],
    },
)
async def feishu_sheet(url: str, max_rows: int = 100) -> str:
    spreadsheet_token, sheet_id = _parse_sheet_url(url)
    if not spreadsheet_token:
        return "ERROR: cannot parse spreadsheet token from URL"

    try:
        from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    except ImportError as exc:
        return f"ERROR: feishu module unavailable: {exc}"

    try:
        token = await get_tenant_access_token()
    except Exception as exc:
        return f"ERROR: feishu auth failed: {exc}"

    base = get_feishu_open_base_url()
    # Sheets v3 metainfo 拿到首个 sheet_id（如未指定）
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        if not sheet_id:
            try:
                meta = await client.get(
                    f"{base}/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
                    headers=headers,
                )
                meta.raise_for_status()
                sheets = meta.json().get("data", {}).get("sheets") or []
                if not sheets:
                    return "ERROR: no sheets in spreadsheet"
                sheet_id = sheets[0].get("sheet_id")
            except httpx.HTTPError as exc:
                return f"ERROR: sheet meta failed: {exc}"

        # 读取 A1:Z<max_rows> 区域
        rows_to_read = max(1, min(int(max_rows), 500))
        range_str = f"{sheet_id}!A1:Z{rows_to_read}"
        try:
            r = await client.get(
                f"{base}/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{range_str}",
                headers=headers,
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            return f"ERROR: sheet read failed: {exc}"

    data = r.json().get("data", {}).get("valueRange", {}).get("values") or []
    if not data:
        return "ERROR: sheet is empty"

    out = io.StringIO()
    writer = csv.writer(out)
    for row in data:
        writer.writerow(["" if cell is None else str(cell) for cell in row])
    csv_text = out.getvalue()
    return csv_text[:8000]


# ---------------------------------------------------------------------------
# Tool 4: python_calc — 安全数值计算（不能 I/O，不能 import）
# ---------------------------------------------------------------------------
_SAFE_BUILTINS = {
    "abs": abs, "min": min, "max": max, "sum": sum, "len": len,
    "round": round, "pow": pow, "int": int, "float": float, "str": str,
    "list": list, "tuple": tuple, "dict": dict, "set": set, "range": range,
    "sorted": sorted, "reversed": reversed, "any": any, "all": all,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
}
_SAFE_GLOBALS = {
    "__builtins__": _SAFE_BUILTINS,
    "math": math,
}


@register_tool(
    name="inspect_image",
    description=(
        "对一张图片（http URL 或 base64）进行视觉分析，提取图表数值/截图文字/关键洞察。"
        "适合用户附上业绩仪表盘截图、产品界面、手写白板照等场景。"
        "需要服务端配置 LLM_VISION_MODEL；未配置时返回 'ERROR: vision disabled'。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "image": {
                "type": "string",
                "description": "图片 URL 或 base64 字符串（可加 data:image/png;base64, 前缀）",
            },
            "focus": {
                "type": "string",
                "description": "可选：你想从图片提取的具体焦点（如『提取所有图表数值』）",
            },
        },
        "required": ["image"],
    },
)
async def inspect_image(image: str, focus: str = "") -> str:
    from app.core.vision import _DEFAULT_VISION_PROMPT, analyze_image

    prompt = _DEFAULT_VISION_PROMPT
    if focus:
        prompt = f"{_DEFAULT_VISION_PROMPT}\n\n额外焦点：{focus[:200]}"
    result = await analyze_image(image, prompt=prompt)
    if result is None:
        return "ERROR: vision disabled (set LLM_VISION_MODEL) or call failed"
    return result


@register_tool(
    name="python_calc",
    description=(
        "执行受限的 Python 表达式做数值/统计计算。"
        "可用 math 模块、列表推导、abs/min/max/sum/round 等。"
        "禁止 I/O、文件、网络、import；仅一行表达式。"
        "示例：'sum([100, 98, 112]) / 3' / 'math.sqrt(0.30**2 + 0.20**2)'"
    ),
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "纯计算表达式"},
        },
        "required": ["expression"],
    },
)
async def python_calc(expression: str) -> str:
    expression = (expression or "").strip()
    if not expression:
        return "ERROR: empty expression"
    if any(banned in expression for banned in ("import", "open(", "exec(", "eval(", "__", "compile(")):
        return "ERROR: forbidden token detected"
    if len(expression) > 500:
        return "ERROR: expression too long (>500 chars)"

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: eval(expression, _SAFE_GLOBALS, {})),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        return "ERROR: expression timeout (>2s)"
    except Exception as exc:
        return f"ERROR: {exc}"
    return str(result)[:1000]
