"""v8.6.20-r38: /seed 重复任务保护回归。

避免双击 / 网络重试 / 自动化误触发让 7 岗 LLM 链路重复跑（每条任务约 12-18k tokens）。

锁定契约：
1. 已有相同 title × dimension 的「待分析」记录 → 409 + existing_record_id
2. 已有相同 title 但状态是「已归档」 → 不算冲突，允许新建
3. 已有相同 title 但 dimension 不同 → 不算冲突，允许新建
4. ?force=true → 跳过去重，直接写
5. list_records 抛错 → 不阻塞 seed，正常写入（dedup check 是软保护）
"""
from __future__ import annotations

from types import ModuleType
import sys

import pytest


def _ensure_sse_stub(monkeypatch):
    sse_pkg = ModuleType("sse_starlette")
    sse_mod = ModuleType("sse_starlette.sse")
    sse_mod.EventSourceResponse = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_pkg)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_mod)


def _build_seed_request(monkeypatch):
    """构造一个最小化合法 SeedRequest，只填必填字段。"""
    from app.api import workflow

    return workflow.SeedRequest(
        app_token="app_a",
        table_id="tbl_task",
        title="Q3 经营复盘",
        dimension="综合分析",
    )


@pytest.mark.asyncio
async def test_seed_duplicate_pending_task_returns_409(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops
    from fastapi import HTTPException

    # 模拟 list_records 命中已存在的待分析记录
    async def fake_list(_app, _tid, *, filter_expr=None, max_records=10):
        return [
            {
                "record_id": "rec_existing",
                "fields": {
                    "任务标题": "Q3 经营复盘",
                    "分析维度": "综合分析",
                    "状态": "待分析",
                },
            }
        ]

    create_calls: list = []

    async def fail_create(*args, **kwargs):
        create_calls.append(args)
        return "rec_should_not_be_created"

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)
    monkeypatch.setattr(bitable_ops, "create_record_optional_fields", fail_create)
    monkeypatch.setattr(workflow, "_resolve_seed_template_defaults",
                        lambda *a, **kw: _async_return({}))

    req = _build_seed_request(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await workflow.workflow_seed(req, force=False)
    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail["existing_record_id"] == "rec_existing"
    assert detail["existing_title"] == "Q3 经营复盘"
    assert "force" in detail["advice"].lower() or "force" in detail.get("advice", "")
    # 关键：create_record 不能被调用
    assert create_calls == []


@pytest.mark.asyncio
async def test_seed_force_flag_bypasses_dedup(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    async def fake_list(*_a, **_kw):
        return [{"record_id": "rec_existing", "fields": {"任务标题": "Q3 经营复盘"}}]

    create_calls: list = []

    async def fake_create(_app, _tid, fields, optional_keys=None):
        create_calls.append({"fields": fields})
        return "rec_new_force"

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)
    monkeypatch.setattr(bitable_ops, "create_record_optional_fields", fake_create)
    monkeypatch.setattr(workflow, "_resolve_seed_template_defaults",
                        lambda *a, **kw: _async_return({}))
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    req = _build_seed_request(monkeypatch)
    result = await workflow.workflow_seed(req, force=True)
    assert result["record_id"] == "rec_new_force"
    # force=True：不调 list_records 检查，create 必须发生
    assert len(create_calls) == 1


@pytest.mark.asyncio
async def test_seed_archived_existing_does_not_block(monkeypatch):
    """同 title 但已归档 → list_records 自身的 filter (待分析 OR 分析中) 排除掉，
    所以这里返空 → 允许 seed。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    async def empty_list(*_a, **_kw):
        return []  # 已归档已被 filter_expr 过滤掉

    async def fake_create(_app, _tid, fields, optional_keys=None):
        return "rec_new_after_archive"

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "list_records", empty_list)
    monkeypatch.setattr(bitable_ops, "create_record_optional_fields", fake_create)
    monkeypatch.setattr(workflow, "_resolve_seed_template_defaults",
                        lambda *a, **kw: _async_return({}))
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    req = _build_seed_request(monkeypatch)
    result = await workflow.workflow_seed(req, force=False)
    assert result["record_id"] == "rec_new_after_archive"


@pytest.mark.asyncio
async def test_seed_different_dimension_not_blocked(monkeypatch):
    """同 title 但 dimension 不同 → 不算冲突。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    async def fake_list(*_a, **_kw):
        return [
            {
                "record_id": "rec_data_dim",
                "fields": {"任务标题": "Q3 经营复盘", "分析维度": "数据复盘", "状态": "待分析"},
            }
        ]

    async def fake_create(_app, _tid, fields, optional_keys=None):
        return "rec_new_other_dim"

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)
    monkeypatch.setattr(bitable_ops, "create_record_optional_fields", fake_create)
    monkeypatch.setattr(workflow, "_resolve_seed_template_defaults",
                        lambda *a, **kw: _async_return({}))
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    # 用「综合分析」维度（list 返「数据复盘」），dimension 不匹配应放行
    req = _build_seed_request(monkeypatch)
    result = await workflow.workflow_seed(req, force=False)
    assert result["record_id"] == "rec_new_other_dim"


@pytest.mark.asyncio
async def test_seed_dedup_check_failure_does_not_block_create(monkeypatch):
    """list_records 抛错 → dedup 检查失败 → 仍允许 create（软保护，非硬约束）。"""
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    async def broken_list(*_a, **_kw):
        raise RuntimeError("Bitable API timeout")

    async def fake_create(_app, _tid, fields, optional_keys=None):
        return "rec_new_despite_dedup_err"

    async def fake_record_audit(*_a, **_kw):
        return None

    monkeypatch.setattr(bitable_ops, "list_records", broken_list)
    monkeypatch.setattr(bitable_ops, "create_record_optional_fields", fake_create)
    monkeypatch.setattr(workflow, "_resolve_seed_template_defaults",
                        lambda *a, **kw: _async_return({}))
    monkeypatch.setattr(workflow, "record_audit", fake_record_audit)

    req = _build_seed_request(monkeypatch)
    result = await workflow.workflow_seed(req, force=False)
    assert result["record_id"] == "rec_new_despite_dedup_err"


@pytest.mark.asyncio
async def test_find_duplicate_handles_richtext_title(monkeypatch):
    """辅助函数级别：飞书富文本数组 [{text:"Q3"},...] 应被正确拍平。

    v8.6.20-r48（pytest --randomly audit 修复）：原实现用 `bitable_ops.list_records = fake_list`
    + finally 中 `importlib.reload(bitable_ops)`。reload 会替换 bitable_ops 模块全部
    属性引用 → 其他测试文件 `from bitable_ops import _FIELD_CACHE, field_exists` 早已
    绑定的 OLD 引用瞬间失效，导致 test_v8619_phase0 在 random order 下失败。
    改用 monkeypatch.setattr 配 pytest 自动 restore，零污染。
    """
    from app.api import workflow
    from app.bitable_workflow import bitable_ops

    async def fake_list(_app, _tid, *, filter_expr=None, max_records=10):
        return [
            {
                "record_id": "rec_x",
                "fields": {
                    "任务标题": [{"text": "Q3 经营复盘", "type": "text"}],
                    "分析维度": [{"text": "综合分析", "type": "text"}],
                    "状态": "待分析",
                },
            }
        ]

    monkeypatch.setattr(bitable_ops, "list_records", fake_list)
    result = await workflow._find_duplicate_pending_task(
        "app", "tbl", "Q3 经营复盘", "综合分析"
    )
    assert result is not None
    assert result["record_id"] == "rec_x"


# ---- helpers ----


def _async_return(value):
    """Make a sync function look async — for monkeypatch.setattr on async helpers."""

    async def _impl(*_a, **_kw):
        return value

    return _impl()
