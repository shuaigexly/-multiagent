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

logger = logging.getLogger(__name__)


async def send_group_message(text: str, chat_id: Optional[str] = None) -> dict:
    return await with_retry(_send_group_message_impl, text, chat_id)


async def _send_group_message_impl(text: str, chat_id: Optional[str] = None) -> dict:
    """发送文本消息到群，返回 {"message_id": "..."}"""
    client = get_feishu_client()
    target_chat_id = chat_id or settings.feishu_chat_id
    if not target_chat_id:
        raise ValueError("未配置飞书群 ID (feishu_chat_id)")

    req_body = (
        CreateMessageRequestBody.builder()
        .receive_id(target_chat_id)
        .msg_type("text")
        .content(json.dumps({"text": text}, ensure_ascii=False))
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.to_thread(client.im.v1.message.create, req)
    if not resp.success():
        raise RuntimeError(f"发送群消息失败: {resp.msg}")
    logger.info(f"群消息发送成功: {resp.data.message_id}")
    return {"message_id": resp.data.message_id}


async def send_card_message(title: str, content: str, chat_id: Optional[str] = None) -> dict:
    return await with_retry(_send_card_message_impl, title, content, chat_id)


async def _send_card_message_impl(title: str, content: str, chat_id: Optional[str] = None) -> dict:
    """发送富文本卡片消息"""
    client = get_feishu_client()
    target_chat_id = chat_id or settings.feishu_chat_id
    if not target_chat_id:
        raise ValueError("未配置飞书群 ID")

    card = {
        "config": {"wide_screen_mode": True},
        "elements": [
            {
                "tag": "div",
                "text": {"content": content[:3000], "tag": "lark_md"},
            }
        ],
        "header": {
            "title": {"content": title, "tag": "plain_text"},
            "template": "blue",
        },
    }

    req_body = (
        CreateMessageRequestBody.builder()
        .receive_id(target_chat_id)
        .msg_type("interactive")
        .content(json.dumps(card, ensure_ascii=False))
        .build()
    )
    req = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.to_thread(client.im.v1.message.create, req)
    if not resp.success():
        raise RuntimeError(f"发送卡片消息失败: {resp.msg}")
    return {"message_id": resp.data.message_id}
