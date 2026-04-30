"""v8.6.19 Phase B：search_records / batch_update_records / batch_delete_records。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bitable_workflow.bitable_ops import (
    search_records, batch_update_records, batch_delete_records, list_records, _safe_json,
)


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    r.text = ""
    r.raise_for_status = MagicMock()
    return r


def test_safe_json_rejects_non_object_json():
    resp = _resp(["not", "object"])

    result = _safe_json(resp)

    assert result["code"] == -1
    assert "non-object JSON response" in result["msg"]


@pytest.mark.asyncio
async def test_list_records_clamps_paging_parameters(monkeypatch):
    captured: dict = {}

    async def fake_get(url, headers=None, params=None):
        captured["params"] = params
        return _resp({"code": 0, "data": {"items": [{"record_id": "rec1"}], "has_more": False}})

    mock_client = MagicMock()
    mock_client.get = fake_get
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    rows = await list_records("app", "tbl", page_size=999999, max_records=999999)

    assert rows == [{"record_id": "rec1"}]
    assert captured["params"]["page_size"] == 500


@pytest.mark.asyncio
async def test_list_records_returns_empty_for_non_positive_limits(monkeypatch):
    get_spy = AsyncMock()
    mock_client = MagicMock()
    mock_client.get = get_spy
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)

    rows = await list_records("app", "tbl", page_size=100, max_records=-1)

    assert rows == []
    assert get_spy.await_count == 0


@pytest.mark.asyncio
async def test_search_records_request_body_shape(monkeypatch):
    """请求体 filter/sort/field_names；page_size/page_token 在 query。"""
    captured: dict = {}

    async def fake_post(url, headers=None, params=None, json=None):
        captured["url"] = url
        captured["params"] = params
        captured["body"] = json
        return _resp({"code": 0, "data": {"items": [{"record_id": "rec1"}], "has_more": False}})

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    result = await search_records(
        "app", "tbl",
        filter_conditions=[{"field_name": "状态", "operator": "is", "value": ["待分析"]}],
        sort=[{"field_name": "综合评分", "desc": True}],
        field_names=["任务标题"],
    )
    assert result == [{"record_id": "rec1"}]
    assert captured["params"]["page_size"] > 0
    assert captured["body"]["filter"]["conditions"][0]["field_name"] == "状态"
    assert captured["body"]["sort"][0]["field_name"] == "综合评分"
    assert "field_names" in captured["body"]
    assert "automatic_fields" not in captured["body"]  # 默认 False 不发送


@pytest.mark.asyncio
async def test_search_records_clamps_paging_parameters(monkeypatch):
    captured: dict = {}

    async def fake_post(url, headers=None, params=None, json=None):
        captured["params"] = params
        return _resp({"code": 0, "data": {"items": [{"record_id": "rec1"}], "has_more": False}})

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    rows = await search_records("app", "tbl", page_size=999999, max_records=999999)

    assert rows == [{"record_id": "rec1"}]
    assert captured["params"]["page_size"] == 500


@pytest.mark.asyncio
async def test_search_records_pagination(monkeypatch):
    """has_more=True 自动跟 page_token 翻页。"""
    pages = [
        _resp({"code": 0, "data": {"items": [{"record_id": "a"}], "has_more": True, "page_token": "p2"}}),
        _resp({"code": 0, "data": {"items": [{"record_id": "b"}], "has_more": False}}),
    ]
    call_count = {"n": 0}

    async def fake_post(url, headers=None, params=None, json=None):
        r = pages[call_count["n"]]
        call_count["n"] += 1
        return r

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    result = await search_records("app", "tbl")
    assert [r["record_id"] for r in result] == ["a", "b"]


@pytest.mark.asyncio
async def test_search_records_strips_automatic_fields_on_specific_error(monkeypatch):
    """v4 修订：仅 1254000/1254001 或 message 含 automatic_fields 时剥离重试。"""
    pages = [
        # 第一次带 automatic_fields=True 报错 1254001
        _resp({"code": 1254001, "msg": "Invalid parameter: automatic_fields"}),
        # 第二次不带，成功
        _resp({"code": 0, "data": {"items": [{"record_id": "x"}], "has_more": False}}),
    ]
    sent_bodies: list[dict] = []
    call_count = {"n": 0}

    async def fake_post(url, headers=None, params=None, json=None):
        sent_bodies.append(dict(json or {}))
        r = pages[call_count["n"]]
        call_count["n"] += 1
        return r

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    result = await search_records("app", "tbl", automatic_fields=True)
    assert result == [{"record_id": "x"}]
    assert sent_bodies[0].get("automatic_fields") is True
    assert "automatic_fields" not in sent_bodies[1]


@pytest.mark.asyncio
async def test_search_records_does_not_strip_on_other_error(monkeypatch):
    """非 automatic_fields 错误不剥离参数，直接抛 RuntimeError。"""
    async def fake_post(url, headers=None, params=None, json=None):
        return _resp({"code": 1254005, "msg": "InvalidSort"})

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    with pytest.raises(RuntimeError, match="1254005"):
        await search_records("app", "tbl", automatic_fields=True)


@pytest.mark.asyncio
async def test_batch_update_chunks_at_500(monkeypatch):
    """1201 条切 500/500/201 三片（v4 修订）。"""
    chunks_seen: list[int] = []

    async def fake_post(url, headers=None, json=None):
        chunks_seen.append(len(json["records"]))
        return _resp({"code": 0, "data": {"records": json["records"]}})

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    records = [{"record_id": f"r{i}", "fields": {"x": i}} for i in range(1201)]
    n = await batch_update_records("app", "tbl", records)
    assert n == 1201
    assert chunks_seen == [500, 500, 201]


@pytest.mark.asyncio
async def test_batch_update_falls_back_serial_on_chunk_failure(monkeypatch):
    """整片失败时 fallback 逐条串行 update_record；严禁 gather。"""
    serial_calls: list[str] = []

    async def fake_post(url, headers=None, json=None):
        return _resp({"code": 1254005, "msg": "BatchPartialFail"})

    async def fake_update(app_token, table_id, rid, fields):
        serial_calls.append(rid)

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))
    monkeypatch.setattr("app.bitable_workflow.bitable_ops.update_record", fake_update)

    records = [{"record_id": f"r{i}", "fields": {"x": i}} for i in range(3)]
    n = await batch_update_records("app", "tbl", records)
    assert n == 3
    assert serial_calls == ["r0", "r1", "r2"]  # 严格按顺序，不并发


def test_normalize_singleselect_strips_invisible_chars():
    """v8.6.20：飞书 SingleSelect 字段 invisible 字符会让飞书自动新建 hidden option，
    导致 filter view 命中数对不上。normalize 必须把它们 strip 掉。"""
    from app.bitable_workflow.workflow_agents import _normalize_singleselect, _HEALTH_LABELS_ALLOWED
    # 含 zero-width space
    assert _normalize_singleselect("🟡​ 关注", _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "🟡 关注"
    # 含 NBSP
    assert _normalize_singleselect("🟡 关注", _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "🟡 关注"
    # 末尾空白
    assert _normalize_singleselect("🟡 关注  ", _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "🟡 关注"
    # 干净值原样返回
    assert _normalize_singleselect("🔴 预警", _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "🔴 预警"
    # 不在 allowed 集合 → 兜底
    assert _normalize_singleselect("未知", _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "⚪ 数据不足"
    # 空值 → 兜底
    assert _normalize_singleselect("", _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "⚪ 数据不足"
    assert _normalize_singleselect(None, _HEALTH_LABELS_ALLOWED, "⚪ 数据不足") == "⚪ 数据不足"


def test_priority_score_maps_correctly():
    """v8.6.20：priority_score 替代飞书公式不生效问题。"""
    from app.bitable_workflow.schema import priority_score
    assert priority_score("P0 紧急") == 100
    assert priority_score("P1 高") == 75
    assert priority_score("P2 中") == 50
    assert priority_score("P3 低") == 25
    assert priority_score("") == 25
    assert priority_score(None) == 25
    # 模糊匹配（老 base 优先级值可能含变体）
    assert priority_score("p0") == 100
    assert priority_score("紧急") == 100


def test_health_score_maps_correctly():
    """v8.6.20：health_score 替代健康度数值公式。"""
    from app.bitable_workflow.schema import health_score
    assert health_score("🟢 健康") == 100
    assert health_score("🟡 关注") == 60
    assert health_score("🔴 预警") == 20
    assert health_score("⚪ 数据不足") == 0
    assert health_score(None) == 0
    assert health_score("") == 0


@pytest.mark.asyncio
async def test_create_record_optional_fields_strips_missing_field(monkeypatch):
    """v8.6.20：老 base 缺「健康度数值」/「综合评分」时 create 自动 fallback。"""
    from app.bitable_workflow.bitable_ops import create_record_optional_fields

    calls: list[dict] = []

    async def fake_create(app_token, table_id, fields):
        calls.append(dict(fields))
        if "综合评分" in fields and len(calls) == 1:
            raise RuntimeError("create record failed: code=1254044 msg=FieldNameNotFound")
        return "rec_x"

    monkeypatch.setattr("app.bitable_workflow.bitable_ops.create_record", fake_create)

    rid = await create_record_optional_fields(
        "app", "tbl",
        {"任务标题": "T", "综合评分": 100},
        optional_keys=["综合评分"],
    )
    assert rid == "rec_x"
    assert len(calls) == 2
    assert "综合评分" not in calls[1]


def test_flatten_text_value_handles_feishu_rich_text():
    """v8.6.19 实测发现：search_records / get_record 把 text 字段返回为富文本数组
    [{"text": "...", "type": "text"}]，写回飞书会报 1254060 TextFieldConvFail。
    _flatten_text_value 必须把它拍平成 string。"""
    from app.bitable_workflow.scheduler import _flatten_text_value, _flatten_record_fields
    # 1) 富文本数组 → 拼接 text
    rich = [{"text": "Insight", "type": "text"}, {"text": "Hub", "type": "text"}]
    assert _flatten_text_value(rich) == "InsightHub"
    # 2) 普通 string 不变
    assert _flatten_text_value("plain") == "plain"
    # 3) None 不变
    assert _flatten_text_value(None) is None
    # 4) Number 不变
    assert _flatten_text_value(42) == 42
    # 5) Attachment list（含 file_token 不含 text）原样返回
    att = [{"file_token": "xxx", "name": "chart.png"}]
    assert _flatten_text_value(att) == att
    # 6) _flatten_record_fields 应规范化 dict 内所有 value
    fields = {
        "任务标题": rich,
        "状态": "已完成",
        "进度": 1.0,
        "图表": att,
    }
    flat = _flatten_record_fields(fields)
    assert flat["任务标题"] == "InsightHub"
    assert flat["状态"] == "已完成"
    assert flat["进度"] == 1.0
    assert flat["图表"] == att


@pytest.mark.asyncio
async def test_batch_delete_chunks_at_500(monkeypatch):
    chunks_seen: list[int] = []

    async def fake_post(url, headers=None, json=None):
        chunks_seen.append(len(json["records"]))
        return _resp({"code": 0})

    mock_client = MagicMock()
    mock_client.post = fake_post
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_http_client", lambda: mock_client)
    monkeypatch.setattr("app.bitable_workflow.bitable_ops._get_token", AsyncMock(return_value="t"))

    ids = [f"r{i}" for i in range(501)]
    n = await batch_delete_records("app", "tbl", ids)
    assert n == 501
    assert chunks_seen == [500, 1]
