"""飞书即时消息：发送群消息"""
import asyncio
import json
import logging
import re
from typing import Optional

from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from app.feishu.client import get_feishu_client
from app.feishu.retry import with_retry
from app.core.settings import settings
from app.core.redaction import redact_sensitive_text
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
        raise RuntimeError(f"发送消息失败: {redact_sensitive_text(resp.msg, max_chars=500)}")
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
    logger.info("群消息发送成功")
    return result


async def send_card_message(
    title: str,
    content: str,
    chat_id: Optional[str] = None,
    *,
    header_color: str = "blue",
    action_url: Optional[str] = None,
    fields: Optional[list] = None,
) -> dict:
    """v8.6.19：保留旧 positional 签名（title, content, chat_id），新增 keyword-only：
      - header_color: 飞书卡片 header 模板色 (blue/green/yellow/red/...)
      - action_url:   非空时附 action button，标题"打开"
      - fields:       list[(label, value)]，渲染为多行 div；label ≤ 30，value ≤ 200，空过滤
    """
    return await with_retry(
        _send_card_message_impl, title, content, chat_id,
        header_color, action_url, fields,
    )


_VALID_HEADER_COLORS = {"blue", "wathet", "turquoise", "green", "yellow", "orange", "red", "carmine", "violet", "purple", "indigo", "grey"}


# v8.6.20-r9（审计 #5 安全）：飞书 lark_md 会解析 <at user_id="all"></at>、
# <at user_id="ou_xxx"></at>、<a href>、<img> 等控制语法。LLM raw_output 直接进
# lark_md → 注入 @all / 钓鱼链接 / 图片广告。这里把这些标签的 `<` 换成全角 `＜`，
# 让飞书把它当字面文字渲染。仅触发 lark_md 解析的标签前缀做替换，常规文本不影响。
_LARK_MD_DANGEROUS_PATTERNS = re.compile(
    r"<(/?(?:at|a |a\b|img|button|font|action))",
    re.IGNORECASE,
)


def _sanitize_lark_md(text: str) -> str:
    if not text:
        return ""
    return _LARK_MD_DANGEROUS_PATTERNS.sub(r"＜\1", text)


def _normalize_card_fields(fields: Optional[list]) -> list[tuple[str, str]]:
    """规范化 fields：过滤空、截断 label/value，丢弃非 (str, str) 项。"""
    out: list[tuple[str, str]] = []
    if not fields:
        return out
    for item in fields:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        label, value = str(item[0] or "").strip(), str(item[1] or "").strip()
        if not label or not value:
            continue
        # v8.6.20-r9（审计 #5）：fields 也做 lark_md 安全消毒
        out.append((label[:30], _sanitize_lark_md(value[:200])))
    return out


async def _send_card_message_impl(
    title: str,
    content: str,
    chat_id: Optional[str] = None,
    header_color: str = "blue",
    action_url: Optional[str] = None,
    fields: Optional[list] = None,
) -> dict:
    """发送富文本卡片消息"""
    target_chat_id = chat_id or settings.feishu_chat_id
    if not target_chat_id:
        raise ValueError("未配置飞书群 ID")

    template = header_color if header_color in _VALID_HEADER_COLORS else "blue"
    # v8.6.20-r9（审计 #5）：content 来自 LLM raw_output，必须先 sanitize lark_md
    # 控制标签防 @all / 钓鱼链接 / img 注入。
    safe_content = _sanitize_lark_md(truncate_with_marker(content, 3000))
    elements: list[dict] = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": safe_content},
        }
    ]
    norm_fields = _normalize_card_fields(fields)
    if norm_fields:
        elements.append({"tag": "hr"})
        for label, value in norm_fields:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{label}**\n{value}"},
            })
    if action_url:
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "打开"},
                    "url": action_url,
                    "type": "primary",
                }
            ],
        })

    # v8.6.20-r8（审计 #2）：飞书卡片 plain_text 标题硬上限 ~250 字符，超长会
    # 触发 MessageContentInvalid。task_title 来自 SeedRequest（无 max_length）/
    # 或 LLM 生成的跟进任务标题，必须截断。
    safe_title = truncate_with_marker(title, 200, "…")
    card = {
        "schema": "2.0",
        "body": {"elements": elements},
        "header": {
            "title": {"tag": "plain_text", "content": safe_title},
            "template": template,
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
