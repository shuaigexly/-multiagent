"""v8.6.16：base_picker — 用 mock httpx 验证列 base / 表 / 字段 + 分页 + 错误兜底。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.feishu.base_picker import list_user_bases, list_tables, list_fields


def _mock_response(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    return r


@pytest.mark.asyncio
async def test_list_user_bases_filters_only_bitable():
    """drive/v1/files 返回多种 type，只保留 type=bitable。"""
    fake_files = [
        {"token": "doc1", "name": "文档", "type": "docx", "url": "u1"},
        {"token": "tok_a", "name": "我的 base A", "type": "bitable", "url": "ua"},
        {"token": "sht1", "name": "表格", "type": "sheet", "url": "u2"},
        {"token": "tok_b", "name": "B 项目数据", "type": "bitable", "url": "ub", "modified_time": "1"},
    ]
    payload = {"code": 0, "data": {"files": fake_files, "has_more": False}}

    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=_mock_response(payload))
        bases = await list_user_bases("u-fake-token")

    assert len(bases) == 2
    assert {b["app_token"] for b in bases} == {"tok_a", "tok_b"}
    assert bases[0]["name"] == "我的 base A"


@pytest.mark.asyncio
async def test_list_user_bases_pagination():
    """has_more=True 时翻页，合并所有 page。"""
    page1 = {"code": 0, "data": {
        "files": [{"token": "a", "name": "A", "type": "bitable"}],
        "has_more": True, "next_page_token": "p2",
    }}
    page2 = {"code": 0, "data": {
        "files": [{"token": "b", "name": "B", "type": "bitable"}],
        "has_more": False,
    }}
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(side_effect=[
            _mock_response(page1), _mock_response(page2),
        ])
        bases = await list_user_bases("u-fake")
    assert len(bases) == 2


@pytest.mark.asyncio
async def test_list_user_bases_raises_on_api_error():
    payload = {"code": 99991663, "msg": "permission denied"}
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=_mock_response(payload, status=200))
        with pytest.raises(RuntimeError, match="permission denied"):
            await list_user_bases("u-fake")


@pytest.mark.asyncio
async def test_list_tables_returns_items():
    payload = {"code": 0, "data": {"items": [
        {"table_id": "tbl_x", "name": "任务表", "revision": 1},
    ]}}
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=_mock_response(payload))
        tables = await list_tables("app_x", "u-fake")
    assert tables[0]["table_id"] == "tbl_x"


@pytest.mark.asyncio
async def test_list_fields_returns_items():
    payload = {"code": 0, "data": {"items": [
        {"field_id": "fld_a", "field_name": "标题", "type": 1, "is_primary": True},
        {"field_id": "fld_b", "field_name": "状态", "type": 3, "is_primary": False},
    ]}}
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=_mock_response(payload))
        fields = await list_fields("app_x", "tbl_x", "u-fake")
    assert len(fields) == 2
    assert fields[0]["is_primary"] is True
