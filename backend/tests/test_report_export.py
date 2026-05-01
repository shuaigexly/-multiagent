"""v8.6.20-r34: 任务报告 Markdown 导出回归。

锁定契约：
1. 主任务字段、CEO 综合报告、七岗输出、证据链、动作、复核历史按顺序拼接
2. 富文本数组 [{text:"..."}] 自动拍平为字符串
3. 缺失从表（list_records 抛错或返空）不影响其他段落
4. record_id 不存在 → ValueError
5. /export/{record_id} 端点：返 text/markdown；download=1 加 Content-Disposition
"""
from __future__ import annotations

from types import ModuleType
import sys

import pytest
from unittest.mock import AsyncMock


def _ensure_sse_stub(monkeypatch):
    sse_pkg = ModuleType("sse_starlette")
    sse_mod = ModuleType("sse_starlette.sse")
    sse_mod.EventSourceResponse = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_pkg)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_mod)


def _task_record(record_id: str = "rec_task") -> dict:
    return {
        "record_id": record_id,
        "fields": {
            "任务标题": [{"text": "Q3 经营复盘", "type": "text"}],
            "任务编号": "T0001",
            "分析维度": "数据复盘",
            "优先级": "P0 紧急",
            "状态": "已完成",
            "综合评分": 92,
            "背景说明": "Q3 GMV 同比下滑 12%，需要全面定位。",
            "工作流路由": "等待拍板",
            "完成时间": "2026-04-30 12:00",
        },
    }


def _output_records() -> list[dict]:
    return [
        {
            "record_id": "rec_o1",
            "fields": {
                "岗位名称": "数据分析师",
                "健康度评级": "🔴",
                "置信度": "5",
                "分析摘要": "GMV 下滑主要由付费用户流失造成。",
                "行动项": "重启 push 召回 + AB 用户分群分析",
            },
        },
        {
            "record_id": "rec_o2",
            "fields": {
                "岗位名称": "财务顾问",
                "健康度评级": "🟡",
                "置信度": "4",
                "分析摘要": "现金流仍有 8 个月缓冲；但市场费效率下降。",
            },
        },
    ]


def _report_records() -> list[dict]:
    return [
        {
            "record_id": "rec_r1",
            "fields": {
                "报告标题": "Q3 经营复盘 - 综合决策报告",
                "综合健康度": "🔴 预警",
                "决策紧急度": 5,
                "决策摘要": "建议本季度暂缓新功能投入，集中预算到付费召回。",
                "A/B 选项": "A：召回为主 / B：拉新为主",
            },
        }
    ]


def _evidence_records() -> list[dict]:
    return [
        {
            "record_id": "rec_e1",
            "fields": {
                "证据标题": "付费用户月留存数据",
                "证据等级": "硬证据",
                "证据用途": "风险证据",
                "证据内容": "M1=42%, M2=28%, M3=18%（业内基准 35%）",
            },
        }
    ]


def _action_records() -> list[dict]:
    return [
        {
            "record_id": "rec_a1",
            "fields": {
                "动作标题": "启动 push 召回 V1",
                "动作类型": "执行动作",
                "动作状态": "执行中",
                "负责人": "运营负责人",
                "截止时间": "2026-05-15",
            },
        }
    ]


@pytest.mark.asyncio
async def test_assemble_task_markdown_full_path(monkeypatch):
    from app.bitable_workflow import bitable_ops, report_export

    async def fake_get_record(_app, _tid, rid):
        return _task_record(rid)

    async def fake_list_records(_app, table_id, *, filter_expr=None, max_records=50):
        if table_id == "tbl_output":
            return _output_records()
        if table_id == "tbl_report":
            return _report_records()
        if table_id == "tbl_evidence":
            return _evidence_records()
        if table_id == "tbl_action":
            return _action_records()
        return []

    monkeypatch.setattr(bitable_ops, "get_record", fake_get_record)
    monkeypatch.setattr(bitable_ops, "list_records", fake_list_records)

    md = await report_export.assemble_task_markdown(
        app_token="app_xyz",
        table_ids={
            "task": "tbl_task",
            "output": "tbl_output",
            "report": "tbl_report",
            "evidence": "tbl_evidence",
            "action": "tbl_action",
            "review_history": "tbl_rh",
        },
        record_id="rec_task",
    )

    # 富文本数组应被拍平
    assert "Q3 经营复盘" in md
    assert "[{'text'" not in md  # 不应残留 dict repr

    # 顺序：标题 → 元数据 → 背景 → CEO → 七岗 → 证据 → 动作
    title_idx = md.index("# Q3 经营复盘")
    meta_idx = md.index("## 任务元数据")
    bg_idx = md.index("## 背景说明")
    ceo_idx = md.index("## CEO 综合报告")
    agents_idx = md.index("## 七岗 Agent 分析")
    evidence_idx = md.index("## 证据链")
    actions_idx = md.index("## 交付动作")
    assert title_idx < meta_idx < bg_idx < ceo_idx < agents_idx < evidence_idx < actions_idx

    # 关键字段被渲染
    assert "T0001" in md  # 任务编号
    assert "P0 紧急" in md  # 优先级
    assert "数据分析师" in md
    assert "🔴" in md
    assert "财务顾问" in md
    assert "决策摘要" not in md  # 字段名不应直接出现，只渲染值
    assert "建议本季度暂缓新功能投入" in md
    assert "硬证据" in md
    assert "启动 push 召回 V1" in md


@pytest.mark.asyncio
async def test_assemble_skips_missing_subtables(monkeypatch):
    """缺一个从表时其他段落仍要正常输出。"""
    from app.bitable_workflow import bitable_ops, report_export

    async def fake_get_record(_app, _tid, rid):
        return _task_record(rid)

    async def fake_list_records(_app, table_id, *, filter_expr=None, max_records=50):
        if table_id == "tbl_evidence":
            raise RuntimeError("simulate evidence table broken")
        if table_id == "tbl_output":
            return _output_records()
        return []

    monkeypatch.setattr(bitable_ops, "get_record", fake_get_record)
    monkeypatch.setattr(bitable_ops, "list_records", fake_list_records)

    md = await report_export.assemble_task_markdown(
        app_token="app",
        table_ids={"task": "tbl_task", "output": "tbl_output", "evidence": "tbl_evidence"},
        record_id="rec_t",
    )
    assert "## 任务元数据" in md
    assert "## 七岗 Agent 分析" in md
    # 证据链段落应被跳过
    assert "## 证据链" not in md


@pytest.mark.asyncio
async def test_assemble_raises_on_unknown_record(monkeypatch):
    from app.bitable_workflow import bitable_ops, report_export

    async def fake_get_record(*args, **kwargs):
        return {"record_id": "rec_x", "fields": {}}  # 空字段 = 任务不存在

    monkeypatch.setattr(bitable_ops, "get_record", fake_get_record)

    with pytest.raises(ValueError, match="未找到"):
        await report_export.assemble_task_markdown(
            app_token="app",
            table_ids={"task": "tbl_task"},
            record_id="rec_x",
        )


@pytest.mark.asyncio
async def test_export_endpoint_returns_markdown_with_download_header(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import report_export

    async def fake_assemble(*args, **kwargs):
        return "# 测试任务\n\n内容"

    monkeypatch.setattr(report_export, "assemble_task_markdown", fake_assemble)
    monkeypatch.setattr(workflow, "assemble_task_markdown", fake_assemble, raising=False)
    # 上面 raising=False 因为 assemble_task_markdown 是模块内 import 局部符号

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()
    workflow._set_state(
        "app_export",
        app_token="app_export",
        table_ids={"task": "tbl_task", "report": "tbl_r", "output": "tbl_o"},
    )

    resp = await workflow.workflow_export_task(
        record_id="rec_export_1",
        app_token="app_export",
        download=True,
    )
    body = resp.body.decode("utf-8") if isinstance(resp.body, bytes) else resp.body
    assert "# 测试任务" in body
    assert resp.media_type.startswith("text/markdown")
    assert "attachment" in resp.headers["Content-Disposition"]
    assert ".md" in resp.headers["Content-Disposition"]


@pytest.mark.asyncio
async def test_export_endpoint_409_when_base_not_setup(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from fastapi import HTTPException

    workflow._state_by_token.clear()
    workflow._active_token = ""
    workflow._state.clear()

    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_export_task(
            record_id="rec_x",
            app_token=None,
            download=False,
        )
    assert exc.value.status_code == 409
    assert "setup" in exc.value.detail.lower() or "base" in exc.value.detail
