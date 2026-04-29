"""内置工具 — 在应用启动时通过装饰器自动注册到 tools._REGISTRY。

工具使用原则：
  1. 只读为主，不主动改写飞书数据
  2. 网络请求严格超时（< 15s）+ 内容截断
  3. 任何出错都不能抛异常给 LLM —— 返回 'ERROR: ...' 文本，由模型决定降级
"""
from __future__ import annotations

import ast
import asyncio
import csv
import io
import logging
import math
import re
from typing import Any

import httpx

from app.agents.tools import register_tool
from app.core.url_safety import UnsafeURL, fetch_public_url_bytes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool 1: fetch_url — 抓取网页文本（HTML 简单去标签）
# ---------------------------------------------------------------------------
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_FETCH_MAX_BYTES = 512 * 1024
_TEXT_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/csv",
)


def _strip_html(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _decode_response_text(content: bytes, headers: httpx.Headers) -> str:
    ctype = headers.get("content-type", "")
    charset = "utf-8"
    if "charset=" in ctype.lower():
        charset = ctype.lower().rsplit("charset=", 1)[-1].split(";", 1)[0].strip() or charset
    try:
        return content.decode(charset, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


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
    try:
        content, headers, _final_url = await fetch_public_url_bytes(
            url,
            max_bytes=_FETCH_MAX_BYTES,
            timeout=15.0,
            allowed_content_prefixes=_TEXT_CONTENT_TYPES,
        )
        ctype = headers.get("content-type", "")
        body = _decode_response_text(content, headers)
        if "html" in ctype.lower():
            body = _strip_html(body)
        return body[:8000]
    except UnsafeURL as exc:
        return f"ERROR: unsafe url: {exc}"
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
        safe_filter = _validate_bitable_filter(filter)
        rows = await bitable_ops.list_records(
            app_token,
            table_id,
            filter_expr=safe_filter or None,
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


def _validate_bitable_filter(filter_expr: str) -> str:
    expr = (filter_expr or "").strip()
    if not expr:
        return ""
    if len(expr) > 500:
        raise ValueError("filter too long")
    if any(ch in expr for ch in ("\r", "\n", ";", "{", "}")):
        raise ValueError("filter contains forbidden characters")
    if not expr.startswith(("CurrentValue.", "AND(", "OR(", "NOT(")):
        raise ValueError("filter must start with CurrentValue., AND(, OR(, or NOT(")
    return expr


class _SafeCalcValidator(ast.NodeVisitor):
    _allowed_binops = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
    _allowed_unary = (ast.UAdd, ast.USub)
    _allowed_compare = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    _blocked_math_calls = {"factorial", "comb", "perm", "prod"}
    _max_sequence_size = 100_000

    def __init__(self) -> None:
        self.node_count = 0

    def generic_visit(self, node: ast.AST) -> None:
        self.node_count += 1
        if self.node_count > 120:
            raise ValueError("expression too complex")
        super().generic_visit(node)

    def visit_Expression(self, node: ast.Expression) -> None:
        self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> None:
        value = node.value
        if isinstance(value, (int, float)):
            if abs(value) > 1_000_000_000:
                raise ValueError("numeric literal too large")
        elif isinstance(value, str):
            if len(value) > 200:
                raise ValueError("string literal too long")
        elif value is not None and not isinstance(value, bool):
            raise ValueError("literal type is not allowed")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in _SAFE_BUILTINS and node.id != "math":
            raise ValueError(f"name is not allowed: {node.id}")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if not isinstance(node.value, ast.Name) or node.value.id != "math" or node.attr.startswith("_"):
            raise ValueError("only math.<function> attributes are allowed")
        if not hasattr(math, node.attr):
            raise ValueError(f"math attribute is not allowed: {node.attr}")

    def visit_Call(self, node: ast.Call) -> None:
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        if len(node.args) > 20:
            raise ValueError("too many arguments")
        if isinstance(node.func, ast.Name):
            if node.func.id not in _SAFE_BUILTINS:
                raise ValueError(f"function is not allowed: {node.func.id}")
            if node.func.id == "range":
                self._validate_range(node)
            if node.func.id == "pow":
                self._validate_pow(node)
        elif isinstance(node.func, ast.Attribute):
            self.visit_Attribute(node.func)
            if node.func.attr in self._blocked_math_calls:
                raise ValueError(f"math function is too expensive: {node.func.attr}")
            if node.func.attr == "pow":
                self._validate_pow(node)
        else:
            raise ValueError("call target is not allowed")
        for arg in node.args:
            self.visit(arg)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not isinstance(node.op, self._allowed_binops):
            raise ValueError("operator is not allowed")
        if isinstance(node.op, ast.Pow):
            exponent = node.right.value if isinstance(node.right, ast.Constant) else None
            if not isinstance(exponent, (int, float)) or abs(exponent) > 1000:
                raise ValueError("exponent too large")
        if isinstance(node.op, ast.Mult):
            self._validate_repeat(node.left, node.right)
            self._validate_repeat(node.right, node.left)
            sequence_size = self._estimate_sequence_size(node)
            if sequence_size is not None and sequence_size > self._max_sequence_size:
                raise ValueError("sequence result too large")
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not isinstance(node.op, self._allowed_unary):
            raise ValueError("unary operator is not allowed")
        self.visit(node.operand)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if not isinstance(node.op, (ast.And, ast.Or)):
            raise ValueError("boolean operator is not allowed")
        for value in node.values:
            self.visit(value)

    def visit_Compare(self, node: ast.Compare) -> None:
        self.visit(node.left)
        for op in node.ops:
            if not isinstance(op, self._allowed_compare):
                raise ValueError("comparison operator is not allowed")
        for comparator in node.comparators:
            self.visit(comparator)

    def visit_List(self, node: ast.List) -> None:
        self._visit_sequence(node.elts)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        self._visit_sequence(node.elts)

    def visit_Set(self, node: ast.Set) -> None:
        self._visit_sequence(node.elts)

    def visit_Dict(self, node: ast.Dict) -> None:
        if len(node.keys) > 100:
            raise ValueError("literal too large")
        for key, value in zip(node.keys, node.values):
            if key is not None:
                self.visit(key)
            self.visit(value)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        raise ValueError("comprehensions are not allowed")

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp
    visit_Lambda = visit_ListComp
    visit_Subscript = visit_ListComp

    def _visit_sequence(self, elts: list[ast.AST]) -> None:
        if len(elts) > 100:
            raise ValueError("literal too large")
        for elt in elts:
            self.visit(elt)

    def _validate_range(self, node: ast.Call) -> None:
        for arg in node.args:
            if not isinstance(arg, ast.Constant) or not isinstance(arg.value, int):
                raise ValueError("range arguments must be integer literals")
            if abs(arg.value) > 10_000:
                raise ValueError("range argument too large")

    def _validate_pow(self, node: ast.Call) -> None:
        if len(node.args) >= 2:
            exponent = node.args[1].value if isinstance(node.args[1], ast.Constant) else None
            if not isinstance(exponent, (int, float)) or abs(exponent) > 1000:
                raise ValueError("exponent too large")

    def _validate_repeat(self, maybe_count: ast.AST, repeated: ast.AST) -> None:
        if not isinstance(maybe_count, ast.Constant) or not isinstance(maybe_count.value, int):
            return
        if self._estimate_sequence_size(repeated) is None:
            return
        if abs(maybe_count.value) > 10_000:
            raise ValueError("repeat count too large")

    def _estimate_sequence_size(self, node: ast.AST) -> int | None:
        """Return a conservative size estimate for literal sequence expressions."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, bytes, tuple)):
                return len(node.value)
            return None
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return len(node.elts)
        if isinstance(node, ast.Dict):
            return len(node.keys)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left_size = self._estimate_sequence_size(node.left)
            right_size = self._estimate_sequence_size(node.right)
            if isinstance(node.left, ast.Constant) and isinstance(node.left.value, int) and right_size is not None:
                return abs(node.left.value) * right_size
            if isinstance(node.right, ast.Constant) and isinstance(node.right.value, int) and left_size is not None:
                return left_size * abs(node.right.value)
        return None


def _validate_calc_expression(expression: str) -> ast.Expression:
    tree = ast.parse(expression, mode="eval")
    _SafeCalcValidator().visit(tree)
    return tree


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
        "可用 math 模块、abs/min/max/sum/round/range 等纯计算能力。"
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
    try:
        tree = _validate_calc_expression(expression)
        code = compile(tree, "<python_calc>", "eval")
    except Exception as exc:
        return f"ERROR: unsafe expression: {exc}"

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: eval(code, _SAFE_GLOBALS, {})),
            timeout=2.0,
        )
    except asyncio.TimeoutError:
        return "ERROR: expression timeout (>2s)"
    except Exception as exc:
        return f"ERROR: {exc}"
    return str(result)[:1000]
