"""飞书用户 Token 内存缓存（用于需要用户级授权的 API）"""

import logging

import httpx
from sqlalchemy import select

from app.core.settings import (
    get_feishu_app_id,
    get_feishu_app_secret,
    get_feishu_region,
)
from app.feishu.token_crypto import encrypt_token
from app.models.database import AsyncSessionLocal, UserConfig

logger = logging.getLogger(__name__)

_user_access_token: str | None = None
_user_refresh_token: str | None = None
_user_open_id: str | None = None


def get_user_access_token() -> str | None:
    return _user_access_token


def set_user_access_token(token: str | None) -> None:
    global _user_access_token
    _user_access_token = token


def get_user_refresh_token() -> str | None:
    return _user_refresh_token


def set_user_refresh_token(token: str | None) -> None:
    global _user_refresh_token
    _user_refresh_token = token


def get_user_open_id() -> str | None:
    return _user_open_id


def set_user_open_id(open_id: str | None) -> None:
    global _user_open_id
    _user_open_id = open_id


def _feishu_base() -> str:
    return "https://open.larksuite.com" if get_feishu_region() == "intl" else "https://open.feishu.cn"


async def refresh_user_token() -> None:
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
                ("feishu_user_access_token", encrypted_access_token),
                ("feishu_user_refresh_token", encrypted_refresh_token),
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

    set_user_access_token(new_access_token)
    set_user_refresh_token(new_refresh_token)

    logger.info("飞书用户 access_token 已刷新并写回数据库")
