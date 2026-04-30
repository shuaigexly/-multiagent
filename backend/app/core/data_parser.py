"""结构化输入 → 标准化 DataSummary，供 Agent 统一读取。

v8.6.20-r29 起支持的格式（按检测优先级）：
  - JSON / JSONL（数组对象 / 行式 JSON 流）
  - CSV / TSV / 分号分隔 / 管道分隔（用 csv.Sniffer 自动判别 delimiter）
  - Markdown（.md 后缀或 # / ## 显式 heading）
  - 纯文本（兜底）

历史窄口（仅 RFC 4180 CSV + Markdown）已不再适用，README「已知运行边界」对应条目同步收紧。
"""
import csv
import io
import json
from typing import Optional

from pydantic import BaseModel

from app.core.text_utils import truncate_with_marker

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


_BOM_PREFIXES = ("﻿", "￾")
_SNIFFER_SAMPLE_BYTES = 4096
_SNIFFER_DELIMITERS = ",\t;|"


class DataSummary(BaseModel):
    raw_preview: str          # 前10行原始内容
    columns: list[str]        # 表格列名（纯文本则为空）
    row_count: int            # 行数（纯文本则为段落数）
    basic_stats: dict         # pandas describe() 结果（数值列）
    content_type: str         # "csv" | "tsv" | "json" | "jsonl" | "text" | "markdown"
    full_text: str            # 完整内容（限 8000 字符）


def _strip_bom(content: str) -> str:
    for bom in _BOM_PREFIXES:
        if content.startswith(bom):
            return content[len(bom):]
    return content


def _sniff_delimiter(sample: str) -> Optional[str]:
    """用 csv.Sniffer 在前 4KB 里判 delimiter；失败返回 None。"""
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=_SNIFFER_DELIMITERS)
    except csv.Error:
        return None
    return dialect.delimiter


def _content_type_for_delimiter(delimiter: str) -> str:
    return {",": "csv", "\t": "tsv", ";": "csv", "|": "csv"}.get(delimiter, "csv")


def parse_csv(content: str, *, delimiter: str = ",") -> DataSummary:
    """解析单字符 delimiter 表格（CSV / TSV / 分号 / 管道）。

    用 csv 模块做 RFC 4180 兼容（包含字段内嵌套引号 + `"Smith, Inc.",2024` 的逗号），
    再交给 pandas 做 describe — 走 csv.Sniffer 检测的 delimiter 路径。
    pandas 不可用时降级返回原始预览。
    """
    if not HAS_PANDAS:
        return DataSummary(
            raw_preview=truncate_with_marker(content, 1000),
            columns=[],
            row_count=content.count("\n"),
            basic_stats={},
            content_type=_content_type_for_delimiter(delimiter),
            full_text=truncate_with_marker(content, 8000),
        )
    # v8.6.20-r12（审计 #5）：上传层只限文件 5MB，但 CSV 在 pandas 里可膨胀 10–20×。
    # 一份 5MB × 数万列的恶意 CSV 用 dtype 推断 + describe 能让单进程 RSS 飙到 1GB+。
    # 加 nrows=10000 + 列数硬截断，并在列数 > 50 时跳过 describe。
    df = pd.read_csv(io.StringIO(content), nrows=10000, low_memory=False, sep=delimiter)
    if df.shape[1] > 200:
        df = df.iloc[:, :200]
    preview = df.head(10).to_string(index=False)
    stats = {}
    if df.shape[1] <= 50:
        try:
            stats = df.describe().to_dict()
            stats = {
                col: {k: round(v, 4) for k, v in col_stats.items()}
                for col, col_stats in stats.items()
            }
        except Exception:
            pass
    return DataSummary(
        raw_preview=preview,
        columns=list(df.columns),
        row_count=len(df),
        basic_stats=stats,
        content_type=_content_type_for_delimiter(delimiter),
        full_text=truncate_with_marker(content, 8000),
    )


def parse_text(content: str, content_type: str = "text") -> DataSummary:
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    preview = "\n\n".join(paragraphs[:5])
    return DataSummary(
        raw_preview=preview,
        columns=[],
        row_count=len(paragraphs),
        basic_stats={},
        content_type=content_type,
        full_text=truncate_with_marker(content, 8000),
    )


def parse_json(content: str) -> Optional[DataSummary]:
    """支持 JSON 数组对象（list[dict]）和 JSONL（每行一个 dict）。

    返回 None 表示不识别为 JSON，让上层走下一个候选。
    """
    stripped = content.strip()
    if not stripped:
        return None

    # 整体是合法 JSON
    if stripped[0] in "[{":
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, list) and obj and all(isinstance(item, dict) for item in obj):
            return _summarize_dict_records(obj, content_type="json", full_text=content)
        if isinstance(obj, dict):
            return DataSummary(
                raw_preview=truncate_with_marker(json.dumps(obj, ensure_ascii=False, indent=2), 1000),
                columns=list(obj.keys()),
                row_count=1,
                basic_stats={},
                content_type="json",
                full_text=truncate_with_marker(content, 8000),
            )

    # JSONL：每行一个 dict
    lines = [line for line in stripped.splitlines() if line.strip()]
    if len(lines) >= 2 and all(line.lstrip().startswith("{") for line in lines[:5]):
        records = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                return None
            if not isinstance(row, dict):
                return None
            records.append(row)
        return _summarize_dict_records(records, content_type="jsonl", full_text=content)
    return None


def _summarize_dict_records(records: list[dict], *, content_type: str, full_text: str) -> DataSummary:
    """list[dict] → DataSummary：合并所有 key 作 columns，前 10 条 pretty-print 作预览。"""
    columns: list[str] = []
    seen: set[str] = set()
    for row in records:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                columns.append(str(key))
    preview = json.dumps(records[:10], ensure_ascii=False, indent=2)
    stats: dict = {}
    if HAS_PANDAS and records:
        try:
            df = pd.DataFrame(records[:10000])
            if df.shape[1] <= 50:
                stats = df.describe(include="all").fillna("").astype(str).to_dict()
        except Exception:
            stats = {}
    return DataSummary(
        raw_preview=truncate_with_marker(preview, 2000),
        columns=columns[:200],
        row_count=len(records),
        basic_stats=stats,
        content_type=content_type,
        full_text=truncate_with_marker(full_text, 8000),
    )


def parse_content(content: str, filename: Optional[str] = None) -> DataSummary:
    """统一入口：按文件后缀 / 内容嗅探 / 兜底文本三段式判别。"""
    content = _strip_bom(content)
    lowered_filename = filename.lower() if filename else ""

    # 1) 文件后缀强引导（用户显式给了类型就别瞎猜）
    if lowered_filename.endswith(".csv"):
        return parse_csv(content, delimiter=",")
    if lowered_filename.endswith(".tsv"):
        return parse_csv(content, delimiter="\t")
    if lowered_filename.endswith((".jsonl", ".ndjson")):
        json_summary = parse_json(content)
        if json_summary is not None:
            return json_summary
    if lowered_filename.endswith(".json"):
        json_summary = parse_json(content)
        if json_summary is not None:
            return json_summary
    if lowered_filename.endswith(".md"):
        return parse_text(content, content_type="markdown")

    # 2) 内容嗅探 — JSON 优先（首字符 `[` / `{`）
    json_summary = parse_json(content)
    if json_summary is not None:
        return json_summary

    # 3) 表格嗅探 — csv.Sniffer 在前 4KB 里判 delimiter
    sample = content[:_SNIFFER_SAMPLE_BYTES]
    delimiter = _sniff_delimiter(sample)
    lines = content.strip().splitlines()
    if delimiter and len(lines) >= 2:
        try:
            return parse_csv(content, delimiter=delimiter)
        except Exception:
            pass

    # 4) 弱启发兜底（保留 r28 行为）：第一行 ≥2 个逗号且行数 > 2 → CSV
    if len(lines) > 2 and lines[0].count(",") >= 2:
        try:
            return parse_csv(content, delimiter=",")
        except Exception:
            pass

    return parse_text(content)
