"""v8.6.19 Phase C：dashboard_picker / send_card_message / scheduler 完成卡片。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.feishu.dashboard_picker import list_dashboards


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=payload)
    r.text = ""
    return r


@pytest.mark.asyncio
async def test_dashboard_picker_parses_block_id():
    """飞书返回 data.dashboards[].block_id（不是 dashboard_id / items）。"""
    payload = {
        "code": 0,
        "data": {
            "dashboards": [
                {"block_id": "blk_a", "name": "效能仪表盘"},
                {"block_id": "blk_b", "name": "健康度仪表盘"},
            ],
            "has_more": False,
        },
    }
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(return_value=_resp(payload))
        with patch("app.feishu.dashboard_picker.get_tenant_access_token", AsyncMock(return_value="t")):
            dashboards = await list_dashboards("app_x")
    assert dashboards == [
        {"block_id": "blk_a", "name": "效能仪表盘"},
        {"block_id": "blk_b", "name": "健康度仪表盘"},
    ]


@pytest.mark.asyncio
async def test_dashboard_picker_pagination():
    pages = [
        _resp({"code": 0, "data": {
            "dashboards": [{"block_id": "a", "name": "A"}],
            "has_more": True, "page_token": "p2",
        }}),
        _resp({"code": 0, "data": {
            "dashboards": [{"block_id": "b", "name": "B"}],
            "has_more": False,
        }}),
    ]
    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        instance.get = AsyncMock(side_effect=pages)
        with patch("app.feishu.dashboard_picker.get_tenant_access_token", AsyncMock(return_value="t")):
            dashboards = await list_dashboards("app_x")
    assert [d["block_id"] for d in dashboards] == ["a", "b"]


@pytest.mark.asyncio
async def test_dashboard_picker_user_token_priority():
    """传 user_token 时优先用，不调 tenant token。"""
    tenant_called = False
    async def fake_tenant():
        nonlocal tenant_called
        tenant_called = True
        return "TENANT"

    with patch("httpx.AsyncClient") as MockClient:
        instance = MockClient.return_value.__aenter__.return_value
        captured_headers: dict = {}

        async def fake_get(url, headers=None, params=None):
            captured_headers.update(headers or {})
            return _resp({"code": 0, "data": {"dashboards": [], "has_more": False}})

        instance.get = fake_get
        with patch("app.feishu.dashboard_picker.get_tenant_access_token", fake_tenant):
            await list_dashboards("app_x", user_token="USER_TOKEN")

    assert "USER_TOKEN" in captured_headers["Authorization"]
    assert not tenant_called, "传 user_token 不应再调 tenant"


@pytest.mark.asyncio
async def test_send_card_message_old_positional_still_works():
    """v8.6.19 兼容性：老 send_card_message(title, content) 不破。"""
    from app.feishu.im import send_card_message
    sent_content: list[str] = []

    async def fake_send(receive_id, receive_id_type, msg_type, content):
        sent_content.append(content)
        return {"message_id": "m1"}

    with patch("app.feishu.im._send_message_impl", fake_send):
        with patch("app.feishu.im.settings.feishu_chat_id", "fake_chat"):
            await send_card_message("title-x", "content-x")

    assert len(sent_content) == 1
    payload = sent_content[0]
    assert "title-x" in payload
    assert "content-x" in payload
    assert "blue" in payload  # 默认 header_color


@pytest.mark.asyncio
async def test_send_card_message_with_action_button_and_fields():
    """新签名 fields/action_url 渲染为 button + label/value。"""
    from app.feishu.im import send_card_message
    sent_content: list[str] = []

    async def fake_send(receive_id, receive_id_type, msg_type, content):
        sent_content.append(content)
        return {"message_id": "m1"}

    with patch("app.feishu.im._send_message_impl", fake_send):
        with patch("app.feishu.im.settings.feishu_chat_id", "fake_chat"):
            await send_card_message(
                "标题", "内容",
                header_color="green",
                action_url="https://feishu.cn/base/abc?table=t1",
                fields=[("重要机会", "提升 MAU 5%"), ("重要风险", "CAC 上涨")],
            )

    payload = sent_content[0]
    assert "green" in payload  # header_color
    assert "重要机会" in payload
    assert "提升 MAU 5%" in payload
    assert "https://feishu.cn/base/abc" in payload
    assert "button" in payload  # action button


@pytest.mark.asyncio
async def test_send_card_message_truncates_long_label_and_value():
    from app.feishu.im import send_card_message
    sent_content: list[str] = []

    async def fake_send(receive_id, receive_id_type, msg_type, content):
        sent_content.append(content)
        return {"message_id": "m1"}

    long_label = "标签" * 50  # 100 字符
    long_value = "值" * 500
    with patch("app.feishu.im._send_message_impl", fake_send):
        with patch("app.feishu.im.settings.feishu_chat_id", "fake_chat"):
            await send_card_message(
                "t", "c",
                fields=[(long_label, long_value)],
            )

    payload = sent_content[0]
    assert "标签" * 30 not in payload  # 截断到 30 字符
    assert "值" * 201 not in payload  # 截断到 200 字符


@pytest.mark.asyncio
async def test_send_card_message_skips_empty_fields():
    """空 label / value 应被过滤。"""
    from app.feishu.im import send_card_message
    sent_content: list[str] = []

    async def fake_send(receive_id, receive_id_type, msg_type, content):
        sent_content.append(content)
        return {"message_id": "m1"}

    with patch("app.feishu.im._send_message_impl", fake_send):
        with patch("app.feishu.im.settings.feishu_chat_id", "fake_chat"):
            await send_card_message(
                "t", "c",
                fields=[("", "x"), ("y", ""), ("good", "value")],
            )

    payload = sent_content[0]
    assert "good" in payload
    assert "value" in payload
