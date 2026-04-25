"""CardKit v1: send rich agent result cards to Feishu IM groups."""
import json
import logging
from typing import Optional

import httpx

from app.agents.base_agent import AgentResult
from app.core.settings import get_feishu_app_id, get_feishu_app_secret, get_feishu_region
from app.core.text_utils import truncate_with_marker
from app.feishu.client import get_feishu_base_url
from app.feishu.retry import with_retry
from app.feishu.user_token import get_user_access_token

logger = logging.getLogger(__name__)


def _smart_truncate(text: str, max_len: int) -> str:
    """Truncate text intelligently at sentence or bullet boundaries."""
    normalized = text.strip()
    if len(normalized) <= max_len:
        return normalized

    bullet_lines = [
        line.strip()
        for line in normalized.splitlines()
        if line.strip() and (
            line.strip().startswith(("-", "•", "*"))
            or (len(line.strip()) > 1 and line.strip()[0].isdigit() and line.strip()[1] in ".、")
        )
    ]
    if bullet_lines:
        selected: list[str] = []
        current_len = 0
        for bullet in bullet_lines[:3]:
            addition = bullet if not selected else f"\n{bullet}"
            if current_len + len(addition) > max_len:
                break
            selected.append(bullet)
            current_len += len(addition)
        if selected:
            return "\n".join(selected)

    cutoff = min(len(normalized), max_len)
    sentence_candidates = [
        pos for pos in (
            normalized.find("。", 0, cutoff + 1),
            normalized.find("\n", 0, cutoff + 1),
        )
        if pos != -1
    ]
    if sentence_candidates:
        sentence_end = min(sentence_candidates) + 1
        if sentence_end <= cutoff:
            return normalized[:sentence_end].strip()

    truncated = normalized[:cutoff]
    for marker in ("。", "\n", "；", "，", " "):
        boundary = truncated.rfind(marker)
        if boundary >= int(cutoff * 0.5):
            keep_len = boundary if marker == " " else boundary + 1
            return f"{truncated[:keep_len].rstrip()}..."
    return f"{truncated.rstrip()}..."


def _build_card_content(title: str, results: list[AgentResult]) -> dict:
    """Build structured Feishu card with smart content selection."""
    elements = []
    total_actions = sum(
        len([item for item in result.action_items if not item.strip().startswith("[摘要]")])
        for result in results
    )
    elements.append(
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{len(results)} 个分析模块** · {total_actions} 项行动建议",
            },
        }
    )
    elements.append({"tag": "hr"})

    all_actions = " ".join(
        item
        for result in results
        for item in result.action_items
        if not item.strip().startswith("[摘要]")
    )
    header_template = "blue"
    if "风险" in all_actions or "⚠️" in all_actions:
        header_template = "red"
    elif "机会" in all_actions or "增长" in all_actions:
        header_template = "green"

    for index, result in enumerate(results):
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{result.agent_name}**",
                },
            }
        )

        best_section = next(
            (
                section
                for section in result.sections
                if any(keyword in section.title for keyword in ["核心", "结论", "总体", "评估"])
            ),
            result.sections[0] if result.sections else None,
        )
        if best_section:
            content = _smart_truncate(best_section.content, 250)
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{best_section.title}**\n{content}",
                    },
                }
            )

        display_items = [
            item for item in result.action_items if not item.strip().startswith("[摘要]")
        ]
        if display_items:
            items_text = "\n".join(
                f"{'⚠️ ' if ('风险' in item or '⚠️' in item) and not item.startswith('⚠️') else ''}"
                f"{item if ('风险' in item or '⚠️' in item) else f'• {item}'}"
                for item in display_items[:3]
            )
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**行动建议**\n{items_text}",
                    },
                }
            )

        if index < len(results) - 1:
            elements.append({"tag": "hr"})

    return {
        "schema": "2.0",
        "body": {"elements": elements},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": header_template,
        },
    }


async def _send_card_to_chat_impl(chat_id: str, title: str, results: list[AgentResult]) -> dict:
    """Send an agent results card to a Feishu group chat."""
    token = get_user_access_token() or await _get_tenant_access_token()
    api_base_url = _get_feishu_api_base_url()
    user_base_url = get_feishu_base_url()
    card = _build_card_content(title, results)

    payload = {
        "receive_id": chat_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_base_url}/open-apis/im/v1/messages?receive_id_type=chat_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )

    data = _parse_json_response(resp, "CardKit send failed")
    if data.get("code", 0) != 0:
        raise RuntimeError(f"CardKit send failed: {data.get('msg')} (code={data.get('code')})")
    msg_id = data.get("data", {}).get("message_id", "")
    return {"message_id": msg_id, "url": f"{user_base_url}/im/chat/{chat_id}/message/{msg_id}"}


async def send_card_to_chat(chat_id: str, title: str, results: list[AgentResult]) -> dict:
    return await with_retry(_send_card_to_chat_impl, chat_id, title, results)


async def _send_card_to_user_impl(open_id: str, title: str, results: list[AgentResult]) -> dict:
    """发卡片私信给用户（receive_id_type=open_id）"""
    token = get_user_access_token() or await _get_tenant_access_token()
    api_base_url = _get_feishu_api_base_url()
    user_base_url = get_feishu_base_url()
    card = _build_card_content(title, results)

    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_base_url}/open-apis/im/v1/messages?receive_id_type=open_id",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )

    data = _parse_json_response(resp, "CardKit DM send failed")
    if data.get("code", 0) != 0:
        raise RuntimeError(f"CardKit DM send failed: {data.get('msg')} (code={data.get('code')})")

    resp_data = data.get("data", {})
    msg_id = resp_data.get("message_id", "")
    resp_chat_id = resp_data.get("chat_id", "")
    url = f"{user_base_url}/im/chat/{resp_chat_id}/message/{msg_id}" if resp_chat_id else None
    return {"message_id": msg_id, "url": url}


async def send_card_to_user(open_id: str, title: str, results: list[AgentResult]) -> dict:
    return await with_retry(_send_card_to_user_impl, open_id, title, results)


async def _get_tenant_access_token() -> str:
    app_id = get_feishu_app_id()
    app_secret = get_feishu_app_secret()
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID/FEISHU_APP_SECRET are required to send CardKit messages")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_get_feishu_api_base_url()}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )

    data = _parse_json_response(resp, "Failed to fetch Feishu tenant access token")
    if data.get("code", 0) != 0:
        raise RuntimeError(
            f"Failed to fetch Feishu tenant access token: {data.get('msg')} "
            f"(code={data.get('code')})"
        )
    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError("Feishu token response did not include tenant_access_token")
    return token


def _get_feishu_api_base_url() -> str:
    region = get_feishu_region().strip().lower()
    return "https://open.larksuite.com" if region == "intl" else "https://open.feishu.cn"


def _parse_json_response(resp: httpx.Response, context: str) -> dict:
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"{context}: HTTP {resp.status_code}: {truncate_with_marker(resp.text, 500)}"
        ) from exc
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context}: non-JSON response status={resp.status_code}") from exc
    return data
