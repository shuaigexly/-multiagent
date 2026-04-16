"""CardKit v1: send rich agent result cards to Feishu IM groups."""
import json
import logging
from typing import Optional

import httpx

from app.agents.base_agent import AgentResult
from app.core.settings import get_feishu_app_id, get_feishu_app_secret, get_feishu_region
from app.feishu.client import get_feishu_base_url
from app.feishu.user_token import get_user_access_token

logger = logging.getLogger(__name__)


def _build_card_content(title: str, results: list[AgentResult]) -> dict:
    """Build Feishu interactive card JSON from agent results."""
    elements = []
    for result in results:
        elements.append({"tag": "markdown", "content": f"**{result.agent_name}**"})
        for section in result.sections[:3]:
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"**{section.title}**\n{section.content[:300]}",
                }
            )
        if result.action_items:
            items_text = "\n".join(f"- {item}" for item in result.action_items[:5])
            elements.append({"tag": "markdown", "content": f"**行动建议**\n{items_text}"})
        elements.append({"tag": "hr"})

    return {
        "schema": "2.0",
        "body": {"elements": elements},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
    }


async def send_card_to_chat(chat_id: str, title: str, results: list[AgentResult]) -> dict:
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


async def send_card_to_user(open_id: str, title: str, results: list[AgentResult]) -> dict:
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
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{context}: non-JSON response status={resp.status_code}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"{context}: HTTP {resp.status_code}: {data}")
    return data
