"""飞书 Bot 消息处理：解析消息文本、过滤触发条件、回帖。"""
import asyncio
import json
import logging
import re
from typing import Any, Optional

from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

from app.feishu.client import get_feishu_client

logger = logging.getLogger(__name__)


def _get(obj: Any, *path: str) -> Any:
    current = obj
    for key in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def extract_text(p2_event: Any) -> Optional[str]:
    """
    从飞书消息事件中提取纯文本。
    content 是 JSON 字符串（{"text": "...@bot hello"}），需 json.loads 后取 text。
    去除 mention 标记后返回纯任务文本。
    """
    try:
        message_type = _get(p2_event, "event", "message", "message_type")
        if message_type != "text":
            return None
        content = _get(p2_event, "event", "message", "content") or "{}"
        content_obj = json.loads(content)
        text = content_obj.get("text", "")
        text = re.sub(r"@\S+", "", text).strip()
        return text or None
    except Exception as exc:
        logger.warning("extract_text 失败: %s", exc)
        return None


def is_valid_bot_trigger(p2_event: Any, bot_open_id: Optional[str] = None) -> bool:
    """
    过滤规则：
    - sender_type 必须是 user（过滤机器人自发事件，防自回环）
    - message_type 必须是 text
    - p2p 单聊：直接接受
    - group 群聊：必须有 @mention（如果知道 bot_open_id 则精确匹配）
    """
    try:
        sender_type = _get(p2_event, "event", "sender", "sender_type")
        message_type = _get(p2_event, "event", "message", "message_type")
        if sender_type != "user" or message_type != "text":
            return False

        chat_type = _get(p2_event, "event", "message", "chat_type") or "group"
        if chat_type == "p2p":
            return True

        mentions = _get(p2_event, "event", "message", "mentions") or []
        if not mentions:
            return False
        if not bot_open_id:
            return True
        return any(_get(mention, "id", "open_id") == bot_open_id for mention in mentions)
    except Exception as exc:
        logger.warning("is_valid_bot_trigger 检查失败: %s", exc)
        return False


async def reply_text_in_thread(message_id: str, text: str) -> None:
    """在原消息线程回复文本。"""
    if not message_id:
        return

    client = get_feishu_client()
    body = (
        ReplyMessageRequestBody.builder()
        .msg_type("text")
        .content(json.dumps({"text": text}, ensure_ascii=False))
        .reply_in_thread(True)
        .build()
    )
    request = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(body)
        .build()
    )

    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(client.im.v1.message.reply, request),
            timeout=30.0,
        )
        if not response.success():
            logger.warning("Bot 回帖失败 message_id=%s: %s", message_id, response.msg)
    except Exception as exc:
        logger.warning("Bot 回帖异常 message_id=%s: %s", message_id, exc)
