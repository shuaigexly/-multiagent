"""v8.6.20-r29: data_parser 多格式覆盖回归。

历史窄口（仅 RFC 4180 CSV + Markdown）已扩展到：
- TSV（Tab 分隔）
- 分号 / 管道 分隔
- JSON 数组对象 list[dict]
- JSONL（每行一个 dict）
- 含嵌套引号的 RFC 4180 CSV（`"Smith, Inc.",2024`）
- BOM 前缀
"""
from __future__ import annotations

from app.core.data_parser import parse_content


def test_strips_utf8_bom_before_parsing():
    csv_with_bom = "﻿title,value\nfoo,1\nbar,2\n"
    summary = parse_content(csv_with_bom, filename="d.csv")
    assert summary.content_type == "csv"
    assert summary.columns == ["title", "value"]


def test_csv_handles_quoted_comma_inside_cell():
    content = 'company,year\n"Smith, Inc.",2024\n"Acme, LLC",2025\n'
    summary = parse_content(content, filename="d.csv")
    assert summary.content_type == "csv"
    assert summary.columns == ["company", "year"]
    assert summary.row_count == 2


def test_tsv_detected_by_extension():
    content = "name\tscore\nalice\t90\nbob\t85\n"
    summary = parse_content(content, filename="d.tsv")
    assert summary.content_type == "tsv"
    assert summary.columns == ["name", "score"]
    assert summary.row_count == 2


def test_tsv_detected_by_sniffer_when_no_filename():
    content = "name\tscore\nalice\t90\nbob\t85\ncarol\t88\n"
    summary = parse_content(content)
    assert summary.content_type == "tsv"
    assert "name" in summary.columns


def test_semicolon_delimiter_detected_by_sniffer():
    content = "name;city;age\nAlice;Paris;30\nBob;Berlin;42\nCarol;Madrid;28\n"
    summary = parse_content(content)
    assert summary.content_type == "csv"  # 分号也归 csv 大类
    assert summary.columns == ["name", "city", "age"]


def test_pipe_delimiter_detected_by_sniffer():
    content = "name|city|age\nAlice|Paris|30\nBob|Berlin|42\nCarol|Madrid|28\n"
    summary = parse_content(content)
    assert summary.content_type == "csv"
    assert summary.columns == ["name", "city", "age"]


def test_json_array_of_objects():
    content = '[{"name":"alice","score":90},{"name":"bob","score":85}]'
    summary = parse_content(content, filename="d.json")
    assert summary.content_type == "json"
    assert "name" in summary.columns and "score" in summary.columns
    assert summary.row_count == 2


def test_json_detected_without_filename():
    content = '[{"x":1},{"x":2},{"x":3}]'
    summary = parse_content(content)
    assert summary.content_type == "json"
    assert summary.row_count == 3


def test_jsonl_detected_by_content():
    content = '{"row":1,"name":"alice"}\n{"row":2,"name":"bob"}\n{"row":3,"name":"carol"}\n'
    summary = parse_content(content, filename="d.jsonl")
    assert summary.content_type == "jsonl"
    assert summary.row_count == 3
    assert "name" in summary.columns


def test_jsonl_extension_ndjson_also_works():
    content = '{"a":1}\n{"a":2}\n'
    summary = parse_content(content, filename="d.ndjson")
    assert summary.content_type == "jsonl"


def test_markdown_extension_takes_precedence_over_csv_heuristic():
    # 即便正文有逗号也尊重 .md 后缀
    content = "# Title\n\nLine, with, commas\n\nAnother paragraph.\n"
    summary = parse_content(content, filename="d.md")
    assert summary.content_type == "markdown"
    assert summary.columns == []


def test_plain_text_fallback_when_no_structure():
    content = "Just one paragraph.\n\nAnother paragraph here.\n"
    summary = parse_content(content)
    assert summary.content_type == "text"
    assert summary.columns == []


def test_legacy_comma_heuristic_still_works():
    # csv.Sniffer 对极短样本可能失败；保留弱启发兜底
    content = "a,b,c\n1,2,3\n4,5,6\n"
    summary = parse_content(content)
    assert summary.content_type == "csv"
    assert summary.columns == ["a", "b", "c"]


def test_invalid_json_falls_through_to_text():
    content = "{ this is not valid json"
    summary = parse_content(content)
    assert summary.content_type == "text"
