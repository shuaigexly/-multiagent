"""
飞书 Aily AI 适配器（HTTP 直调版，稳定可靠）
将飞书 Aily 会话 API 包装成与 BaseAgent._call_llm 相同的接口。

调用流程：
  1. 获取 Tenant Access Token
  2. POST /open-apis/aily/v1/sessions  → session_id
  3. POST /open-apis/aily/v1/sessions/{session_id}/runs  → run_id
  4. 轮询 GET …/runs/{run_id} 直到 status=COMPLETED
  5. 返回 output[0].content[0].text

需要：
  - 企业开通飞书 AI 功能
  - 在飞书开放平台创建「Aily 智能伙伴」应用
  - 应用申请权限：aily:session
  - 设置环境变量 AILY_APP_ID（Aily 智能伙伴的 App ID，非普通应用 App ID）

参考：https://open.feishu.cn/document/aily
"""
import asyncio
import logging
import os
import time
from typing import Optional

import httpx

from app.core.settings import settings

logger = logging.getLogger(__name__)

_TOKEN_CACHE: dict = {}


async def _get_tenant_access_token() -> str:
    """获取飞书 Tenant Access Token（内存缓存，提前 60 秒刷新）"""
    now = time.time()
    cached = _TOKEN_CACHE.get("token")
    expire = _TOKEN_CACHE.get("expire", 0)
    if cached and now < expire - 60:
        return cached

    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            },
        )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")

    token = data["tenant_access_token"]
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expire"] = now + data.get("expire", 7200)
    return token


async def call_aily(
    user_message: str,
    aily_app_id: Optional[str] = None,
    timeout: float = 120.0,
) -> str:
    """
    通过飞书 Aily API 获取 AI 回复。

    Args:
        user_message: 发给 Aily 的完整消息（system + user 内容合并传入）
        aily_app_id: Aily 智能伙伴 App ID，优先于 AILY_APP_ID 环境变量
        timeout: 最长等待秒数（Aily 属于异步长任务，默认 120s）

    Returns:
        Aily 返回的文本回复

    Raises:
        RuntimeError: 未配置 AILY_APP_ID、超时、或接口报错
    """
    app_id = aily_app_id or os.getenv("AILY_APP_ID", "")
    if not app_id:
        raise RuntimeError(
            "飞书 Aily AI 未配置，请设置 AILY_APP_ID 环境变量。\n"
            "需在飞书开放平台创建「Aily 智能伙伴」并申请 aily:session 权限。\n"
            "文档：https://open.feishu.cn/document/aily"
        )

    base = "https://open.feishu.cn/open-apis/aily/v1"
    token = await _get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30) as http:
        # Step 1: 创建会话
        r = await http.post(
            f"{base}/sessions",
            headers=headers,
            json={"channel_context": {"aily_app_id": app_id}},
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Aily 创建会话失败: code={d.get('code')} msg={d.get('msg')}")
        session_id = d["data"]["session"]["id"]
        logger.debug("Aily session created: %s", session_id)

        # Step 2: 创建运行
        r = await http.post(
            f"{base}/sessions/{session_id}/runs",
            headers=headers,
            json={
                "aily_app_id": app_id,
                "input": [
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_message[:8000]}],
                    }
                ],
            },
        )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Aily 创建运行失败: code={d.get('code')} msg={d.get('msg')}")
        run_id = d["data"]["run"]["id"]
        logger.debug("Aily run created: %s", run_id)

    # Step 3: 轮询等待完成
    deadline = time.monotonic() + timeout
    poll_interval = 2.0

    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)

        # 长任务可能 token 已过期，每次轮询都刷新
        token = await _get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(
                f"{base}/sessions/{session_id}/runs/{run_id}",
                headers=headers,
            )
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Aily 查询状态失败: code={d.get('code')} msg={d.get('msg')}")

        run_status = d["data"]["run"]["status"]
        logger.debug("Aily run %s status: %s", run_id, run_status)

        if run_status == "COMPLETED":
            for msg in d["data"]["run"].get("output", []):
                for item in msg.get("content", []):
                    if item.get("type") == "text" and item.get("text"):
                        return item["text"]
            return "[Aily 返回空回复]"

        if run_status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Aily 运行失败，状态={run_status}")

        # 指数退避，最长 10s 间隔
        poll_interval = min(poll_interval * 1.5, 10.0)

    raise RuntimeError(
        f"Aily 响应超时（{timeout}s），会话={session_id} 运行={run_id}"
    )
