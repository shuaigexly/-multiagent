"""CSV/文本 → 标准化 DataSummary，供 Agent 统一读取"""
import io
from typing import Optional
from pydantic import BaseModel

from app.core.text_utils import truncate_with_marker

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


class DataSummary(BaseModel):
    raw_preview: str          # 前10行原始内容
    columns: list[str]        # CSV 列名（纯文本则为空）
    row_count: int            # 行数（纯文本则为段落数）
    basic_stats: dict         # pandas describe() 结果（数值列）
    content_type: str         # "csv" | "text" | "markdown"
    full_text: str            # 完整内容（限 8000 字符）


def parse_csv(content: str) -> DataSummary:
    if not HAS_PANDAS:
        return DataSummary(
            raw_preview=truncate_with_marker(content, 1000),
            columns=[],
            row_count=content.count("\n"),
            basic_stats={},
            content_type="csv",
            full_text=truncate_with_marker(content, 8000),
        )
    # v8.6.20-r12（审计 #5）：上传层只限文件 5MB，但 CSV 在 pandas 里可膨胀 10–20×。
    # 一份 5MB × 数万列的恶意 CSV 用 dtype 推断 + describe 能让单进程 RSS 飙到 1GB+。
    # 加 nrows=10000 + 列数硬截断，并在列数 > 50 时跳过 describe。
    df = pd.read_csv(io.StringIO(content), nrows=10000, low_memory=False)
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
        content_type="csv",
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


def parse_content(content: str, filename: Optional[str] = None) -> DataSummary:
    lowered_filename = filename.lower() if filename else ""
    if lowered_filename.endswith(".csv"):
        return parse_csv(content)
    if lowered_filename.endswith(".md"):
        return parse_text(content, content_type="markdown")
    # 简单启发：第一行有逗号且行数 > 2 视为 CSV
    lines = content.strip().splitlines()
    if len(lines) > 2 and lines[0].count(",") >= 2:
        try:
            return parse_csv(content)
        except Exception:
            pass
    return parse_text(content)
