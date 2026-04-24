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

from app.core.settings import get_feishu_app_id, get_feishu_app_secret
from app.feishu.client import get_feishu_base_url, get_feishu_region

logger = logging.getLogger(__name__)

_TOKEN_CACHE: dict = {}
_TOKEN_LOCK: asyncio.Lock | None = None


def _get_token_lock() -> asyncio.Lock:
    global _TOKEN_LOCK
    if _TOKEN_LOCK is None:
        _TOKEN_LOCK = asyncio.Lock()
    return _TOKEN_LOCK


def get_feishu_open_base_url() -> str:
    return _get_feishu_open_base_url()


def _get_feishu_open_base_url() -> str:
    base_url = get_feishu_base_url().rstrip("/")
    if base_url.startswith("https://open."):
        return base_url

    region = get_feishu_region().strip().lower()
    return "https://open.larksuite.com" if region == "intl" else "https://open.feishu.cn"


async def get_tenant_access_token() -> str:
    return await _get_tenant_access_token()


async def _get_tenant_access_token() -> str:
    """获取飞书 Tenant Access Token（内存缓存，提前 60 秒刷新）。

    使用 _TOKEN_LOCK 防止多个协程同时发现 token 过期后并发发起多次刷新请求。
    使用 get_feishu_app_id/secret() 确保运行时 DB override 生效。
    """
    now = time.time()
    # Fast path: valid cached token (no lock needed for read)
    if _TOKEN_CACHE.get("token") and now < _TOKEN_CACHE.get("expire", 0) - 60:
        return _TOKEN_CACHE["token"]

    async with _get_token_lock():
        # Double-check under lock: another coroutine may have refreshed while we waited
        if _TOKEN_CACHE.get("token") and now < _TOKEN_CACHE.get("expire", 0) - 60:
            return _TOKEN_CACHE["token"]

        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                f"{_get_feishu_open_base_url()}/open-apis/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": get_feishu_app_id(),
                    "app_secret": get_feishu_app_secret(),
                },
            )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取飞书 token 失败: {data}")

        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"飞书 token 响应缺少 tenant_access_token 字段: {data}")
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

    base = f"{_get_feishu_open_base_url()}/open-apis/aily/v1"
    token = await _get_tenant_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30) as http:
        # Step 1: 创建会话
        r = await http.post(
            f"{base}/sessions",
            headers=headers,
            json={"channel_context": {"aily_app_id": app_id}},
        )
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Aily 创建会话失败: code={d.get('code')} msg={d.get('msg')}")
        try:
            session_id = d["data"]["session"]["id"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Aily 会话响应结构异常: {d}") from exc
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
        r.raise_for_status()
        d = r.json()
        if d.get("code") != 0:
            raise RuntimeError(f"Aily 创建运行失败: code={d.get('code')} msg={d.get('msg')}")
        try:
            run_id = d["data"]["run"]["id"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Aily 运行响应结构异常: {d}") from exc
        logger.debug("Aily run created: %s", run_id)

    # Step 3: 轮询等待完成
    deadline = time.monotonic() + timeout
    poll_interval = 2.0

    async with httpx.AsyncClient(timeout=15) as http:
        while time.monotonic() < deadline:
            await asyncio.sleep(poll_interval)

            # 长任务可能 token 已过期，每次轮询都刷新
            token = await _get_tenant_access_token()
            headers = {"Authorization": f"Bearer {token}"}

            r = await http.get(
                f"{base}/sessions/{session_id}/runs/{run_id}",
                headers=headers,
            )
            r.raise_for_status()
            d = r.json()
            if d.get("code") != 0:
                raise RuntimeError(f"Aily 查询状态失败: code={d.get('code')} msg={d.get('msg')}")

            try:
                run_status = d["data"]["run"]["status"]
            except (KeyError, TypeError) as exc:
                raise RuntimeError(f"Aily 轮询响应结构异常: {d}") from exc
            logger.debug("Aily run %s status: %s", run_id, run_status)

            if run_status == "COMPLETED":
                for msg in d["data"]["run"].get("output", []):
                    for item in msg.get("content", []):
                        if item.get("type") == "text" and item.get("text"):
                            return item["text"]
                raise RuntimeError("Aily returned empty content")

            if run_status in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"Aily 运行失败，状态={run_status}")

            # 指数退避，最长 10s 间隔
            poll_interval = min(poll_interval * 1.5, 10.0)

    raise RuntimeError(
        f"Aily 响应超时（{timeout}s），会话={session_id} 运行={run_id}"
    )
