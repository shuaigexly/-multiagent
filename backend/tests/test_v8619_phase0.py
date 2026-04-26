"""v8.6.19 Phase 0：_safe_json / field_exists / update_record_optional_fields。"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bitable_workflow.bitable_ops import (
    _safe_json, _is_field_missing_error, _invalidate_field_cache,
    _FIELD_CACHE, field_exists, update_record_optional_fields,
)


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    r.text = "..."
    return r


def test_safe_json_handles_non_json_response():
    bad = MagicMock()
    bad.status_code = 502
    bad.text = "<html>502</html>"
    bad.json = MagicMock(side_effect=ValueError("Expecting value"))
    body = _safe_json(bad)
    assert body["code"] == -1
    assert "status=502" in body["msg"]


def test_field_missing_error_excludes_1254043_record_not_found():
    """v4 修订关键：1254043 是 RecordIdNotFound，不能触发 optional fallback。"""
    assert _is_field_missing_error(Exception("code=1254044"))
    assert _is_field_missing_error(Exception("code=1254045"))
    assert _is_field_missing_error(Exception("code=1254046"))
    assert _is_field_missing_error(Exception("FieldNameNotFound xyz"))
    assert _is_field_missing_error(Exception("FieldIdNotFound abc"))
    assert _is_field_missing_error(Exception("field not found"))
    assert not _is_field_missing_error(Exception("code=1254043 RecordIdNotFound"))
    assert not _is_field_missing_error(Exception("some other error"))


@pytest.mark.asyncio
async def test_field_exists_uses_cache(monkeypatch):
    """缓存命中后不再调 API。"""
    _FIELD_CACHE.clear()
    call_count = {"n": 0}

    async def fake_fetch(app_token, table_id):
        call_count["n"] += 1
        names = {"任务标题", "状态"}
        with patch.dict(_FIELD_CACHE, {(app_token, table_id): (names, time.time())}):
            pass
        from app.bitable_workflow import bitable_ops
        bitable_ops._FIELD_CACHE[(app_token, table_id)] = (names, time.time())
        return names

    monkeypatch.setattr("app.bitable_workflow.bitable_ops._fetch_field_names", fake_fetch)
    assert await field_exists("app", "tbl", "状态") is True
    assert await field_exists("app", "tbl", "状态") is True  # cache hit
    assert call_count["n"] == 1, "应只调 1 次 API"


@pytest.mark.asyncio
async def test_field_exists_refresh_force_refetch(monkeypatch):
    """refresh=True 强制重拉。"""
    _FIELD_CACHE.clear()
    call_count = {"n": 0}

    async def fake_fetch(app_token, table_id):
        call_count["n"] += 1
        names = {"综合评分"}
        from app.bitable_workflow import bitable_ops
        bitable_ops._FIELD_CACHE[(app_token, table_id)] = (names, time.time())
        return names

    monkeypatch.setattr("app.bitable_workflow.bitable_ops._fetch_field_names", fake_fetch)
    await field_exists("app", "tbl", "综合评分")
    await field_exists("app", "tbl", "综合评分", refresh=True)
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_invalidate_field_cache_drops_entry():
    """字段创建/失败降级时应主动失效缓存。"""
    _FIELD_CACHE[("app", "tbl")] = ({"a"}, time.time())
    _invalidate_field_cache("app", "tbl")
    assert ("app", "tbl") not in _FIELD_CACHE


@pytest.mark.asyncio
async def test_update_record_optional_fields_strips_on_field_missing(monkeypatch):
    """字段不存在错误（1254044）时移除 optional_keys 后重试一次。"""
    calls: list[dict] = []

    async def fake_update(app_token, table_id, rid, fields):
        calls.append(dict(fields))
        if "完成日期" in fields and len(calls) == 1:
            raise RuntimeError("update record failed: code=1254044 msg=FieldNameNotFound")

    monkeypatch.setattr("app.bitable_workflow.bitable_ops.update_record", fake_update)
    res = await update_record_optional_fields(
        "app", "tbl", "rec1",
        {"状态": "已完成", "完成时间": "2026-01-01", "完成日期": 1234567890000},
        optional_keys=["完成日期"],
    )
    assert res["ok"] is True
    assert res["fallback"] is True
    assert res["removed"] == ["完成日期"]
    assert len(calls) == 2
    assert "完成日期" not in calls[1]


@pytest.mark.asyncio
async def test_update_record_optional_fields_does_not_strip_on_record_not_found(monkeypatch):
    """1254043 RecordIdNotFound 不触发 optional fallback（v4 修订）。"""
    async def fake_update(app_token, table_id, rid, fields):
        raise RuntimeError("update record failed: code=1254043 msg=RecordIdNotFound")

    monkeypatch.setattr("app.bitable_workflow.bitable_ops.update_record", fake_update)
    with pytest.raises(RuntimeError, match="1254043"):
        await update_record_optional_fields(
            "app", "tbl", "rec1",
            {"状态": "已完成", "完成日期": 123},
            optional_keys=["完成日期"],
        )
