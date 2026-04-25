"""飞书即时消息：发送群消息"""
import asyncio
import json
import logging
from typing import Optional

from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from app.feishu.client import get_feishu_client
from app.feishu.retry import with_retry
from app.core.settings import settings
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)


async def _send_message_impl(
    receive_id: str, receive_id_type: str, msg_type: str, content: str
) -> dict:
    """通用消息发送（支持 chat_id 或 open_id）"""
    client = get_feishu_client()
    req_body = (
        CreateMessageRequestBody.builder()
        .receive_id(receive_id)
        .msg_type(msg_type)
        .content(content)
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type(receive_id_type)
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.wait_for(
        asyncio.to_thread(client.im.v1.message.create, req),
        timeout=30.0,
    )
    if not resp.success():
        raise RuntimeError(f"发送消息失败: {resp.msg}")
    return {"message_id": resp.data.message_id}


async def send_group_message(text: str, chat_id: Optional[str] = None) -> dict:
    return await with_retry(_send_group_message_impl, text, chat_id)


async def _send_group_message_impl(text: str, chat_id: Optional[str] = None) -> dict:
    """发送文本消息到群，返回 {"message_id": "..."}"""
    target_chat_id = chat_id or settings.feishu_chat_id
    if not target_chat_id:
        raise ValueError("未配置飞书群 ID (feishu_chat_id)")
    result = await _send_message_impl(
        target_chat_id,
        "chat_id",
        "text",
        json.dumps({"text": text}, ensure_ascii=False),
    )
    logger.info(f"群消息发送成功: {result['message_id']}")
    return result


async def send_card_message(title: str, content: str, chat_id: Optional[str] = None) -> dict:
    return await with_retry(_send_card_message_impl, title, content, chat_id)


async def _send_card_message_impl(title: str, content: str, chat_id: Optional[str] = None) -> dict:
    """发送富文本卡片消息"""
    target_chat_id = chat_id or settings.feishu_chat_id
    if not target_chat_id:
        raise ValueError("未配置飞书群 ID")

    card = {
        "schema": "2.0",
        "body": {
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": truncate_with_marker(content, 3000)},
                }
            ]
        },
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
    }

    return await _send_message_impl(
        target_chat_id,
        "chat_id",
        "interactive",
        json.dumps(card, ensure_ascii=False),
    )


async def send_dm_message(open_id: str, text: str) -> dict:
    """发送文本私信给用户（open_id）"""
    return await with_retry(
        _send_message_impl,
        open_id,
        "open_id",
        "text",
        json.dumps({"text": text}, ensure_ascii=False),
    )


async def send_dm_card(open_id: str, title: str, content: str) -> dict:
    """发送富文本卡片私信给用户（open_id）"""
    card = {
        "schema": "2.0",
        "body": {
            "elements": [
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": truncate_with_marker(content, 3000)},
                }
            ]
        },
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
    }
    return await with_retry(
        _send_message_impl,
        open_id,
        "open_id",
        "interactive",
        json.dumps(card, ensure_ascii=False),
    )
