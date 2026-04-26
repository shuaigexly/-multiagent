"""飞书用户 Token 内存缓存（用于需要用户级授权的 API）"""

import asyncio
import logging

import httpx
from sqlalchemy import select

from app.core.settings import (
    get_feishu_app_id,
    get_feishu_app_secret,
    get_feishu_region,
)
from app.core.observability import get_tenant_id
from app.feishu.token_crypto import encrypt_token
from app.models.database import AsyncSessionLocal, UserConfig

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"
USER_ACCESS_TOKEN_KEY = "feishu_user_access_token"
USER_REFRESH_TOKEN_KEY = "feishu_user_refresh_token"
USER_OPEN_ID_KEY = "feishu_user_open_id"

_user_access_tokens: dict[str, str] = {}
_user_refresh_tokens: dict[str, str] = {}
_user_open_ids: dict[str, str] = {}
_refresh_lock: asyncio.Lock | None = None
import threading as _threading
_refresh_lock_init = _threading.Lock()


def _get_refresh_lock() -> asyncio.Lock:
    """v8.3 修复：懒初始化 race — 并发首次刷新 user OAuth token 各自创建独立锁
    → token 双重刷新（飞书 refresh_token 一次性的，可能让其中一个失败）。
    """
    global _refresh_lock
    if _refresh_lock is None:
        with _refresh_lock_init:
            if _refresh_lock is None:
                _refresh_lock = asyncio.Lock()
    return _refresh_lock


def _tenant_scope(tenant_id: str | None = None) -> str:
    tenant = (tenant_id or get_tenant_id() or DEFAULT_TENANT_ID).strip()
    return tenant or DEFAULT_TENANT_ID


def scoped_config_key(base_key: str, tenant_id: str | None = None) -> str:
    tenant = _tenant_scope(tenant_id)
    if tenant == DEFAULT_TENANT_ID:
        return base_key
    return f"{base_key}:{tenant}"


def tenant_from_config_key(key: str, base_key: str) -> str | None:
    if key == base_key:
        return DEFAULT_TENANT_ID
    prefix = f"{base_key}:"
    if key.startswith(prefix):
        tenant = key[len(prefix):].strip()
        return tenant or None
    return None


def get_user_access_token(tenant_id: str | None = None) -> str | None:
    return _user_access_tokens.get(_tenant_scope(tenant_id))


def set_user_access_token(token: str | None, tenant_id: str | None = None) -> None:
    tenant = _tenant_scope(tenant_id)
    if token:
        _user_access_tokens[tenant] = token
    else:
        _user_access_tokens.pop(tenant, None)


def get_user_refresh_token(tenant_id: str | None = None) -> str | None:
    return _user_refresh_tokens.get(_tenant_scope(tenant_id))


def set_user_refresh_token(token: str | None, tenant_id: str | None = None) -> None:
    tenant = _tenant_scope(tenant_id)
    if token:
        _user_refresh_tokens[tenant] = token
    else:
        _user_refresh_tokens.pop(tenant, None)


def get_user_open_id(tenant_id: str | None = None) -> str | None:
    return _user_open_ids.get(_tenant_scope(tenant_id))


def set_user_open_id(open_id: str | None, tenant_id: str | None = None) -> None:
    tenant = _tenant_scope(tenant_id)
    if open_id:
        _user_open_ids[tenant] = open_id
    else:
        _user_open_ids.pop(tenant, None)


def _feishu_base() -> str:
    return "https://open.larksuite.com" if get_feishu_region() == "intl" else "https://open.feishu.cn"


async def refresh_user_token() -> None:
    async with _get_refresh_lock():
        await _refresh_user_token_impl()


async def _refresh_user_token_impl() -> None:
    tenant_id = _tenant_scope()
    refresh_token = get_user_refresh_token()
    if not refresh_token:
        raise RuntimeError("未找到飞书用户 refresh_token")

    app_id = get_feishu_app_id()
    app_secret = get_feishu_app_secret()
    if not app_id or not app_secret:
        raise RuntimeError("飞书 App ID 或 App Secret 未配置")

    base = _feishu_base()

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            app_token_resp = await client.post(
                f"{base}/open-apis/auth/v3/app_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            app_token_resp.raise_for_status()
            app_token_data = app_token_resp.json()
            app_access_token = app_token_data.get("app_access_token", "")
            if app_token_data.get("code") not in (None, 0):
                raise RuntimeError(
                    f"获取 app_access_token 失败: code={app_token_data.get('code')} "
                    f"msg={app_token_data.get('msg')}"
                )
            if not app_access_token:
                raise RuntimeError("获取 app_access_token 失败: 响应中缺少 app_access_token")

            refresh_resp = await client.post(
                f"{base}/open-apis/authen/v1/refresh_access_token",
                headers={"Authorization": f"Bearer {app_access_token}"},
                json={"grant_type": "refresh_token", "refresh_token": refresh_token},
            )
            refresh_resp.raise_for_status()
            refresh_data = refresh_resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"刷新飞书用户 token 请求失败: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"刷新飞书用户 token 失败: {exc}") from exc

    if refresh_data.get("code") != 0:
        raise RuntimeError(
            f"刷新飞书用户 token 失败: code={refresh_data.get('code')} "
            f"msg={refresh_data.get('msg')} data={refresh_data.get('data')}"
        )

    token_data = refresh_data.get("data") or {}
    new_access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    if not new_access_token or not new_refresh_token:
        raise RuntimeError(f"刷新飞书用户 token 失败: 响应缺少 token 字段 data={token_data}")

    encrypted_access_token = encrypt_token(new_access_token)
    encrypted_refresh_token = encrypt_token(new_refresh_token)

    try:
        async with AsyncSessionLocal() as db:
            for key, value in [
                (scoped_config_key(USER_ACCESS_TOKEN_KEY, tenant_id), encrypted_access_token),
                (scoped_config_key(USER_REFRESH_TOKEN_KEY, tenant_id), encrypted_refresh_token),
            ]:
                existing = await db.execute(select(UserConfig).where(UserConfig.key == key))
                row = existing.scalar_one_or_none()
                if row:
                    row.value = value
                else:
                    db.add(UserConfig(key=key, value=value))
            await db.commit()
    except Exception as exc:
        raise RuntimeError(f"刷新飞书用户 token 后写入数据库失败: {exc}") from exc

    set_user_access_token(new_access_token, tenant_id=tenant_id)
    set_user_refresh_token(new_refresh_token, tenant_id=tenant_id)

    logger.info("飞书用户 access_token 已刷新并写回数据库")
