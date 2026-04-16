"""飞书 OAuth 用户授权（用于获取 user_access_token，支持任务 API 等用户级接口）"""
import logging
import secrets
import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_feishu_app_id, get_feishu_app_secret, get_feishu_region
from app.feishu.user_token import get_user_access_token, set_user_access_token
from app.models.database import UserConfig, get_db

router = APIRouter(prefix="/api/v1/feishu", tags=["feishu-oauth"])
logger = logging.getLogger(__name__)

CALLBACK_PATH = "/api/v1/feishu/oauth/callback"
STATE_TTL_SECONDS = 10 * 60
_pending_states: dict[str, tuple[str, float]] = {}


def _feishu_base() -> str:
    return "https://open.larksuite.com" if get_feishu_region() == "intl" else "https://open.feishu.cn"


def _cleanup_pending_states(now: float | None = None) -> None:
    now = now or time.time()
    expired = [
        token
        for token, (_, created_at) in _pending_states.items()
        if now - created_at > STATE_TTL_SECONDS
    ]
    for token in expired:
        _pending_states.pop(token, None)


def _create_oauth_state(frontend_origin: str) -> str:
    _cleanup_pending_states()
    token = secrets.token_urlsafe(16)
    _pending_states[token] = (frontend_origin, time.time())
    return f"{frontend_origin}|{token}"


def _consume_oauth_state(state: str) -> str:
    _cleanup_pending_states()
    if "|" not in state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    frontend_origin, token = state.rsplit("|", 1)
    pending = _pending_states.pop(token, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    expected_origin, created_at = pending
    if time.time() - created_at > STATE_TTL_SECONDS or frontend_origin != expected_origin:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    return expected_origin


@router.get("/oauth/status")
async def get_oauth_status():
    """检查用户 OAuth 授权状态"""
    return {"authorized": bool(get_user_access_token())}


@router.get("/oauth/url")
async def get_oauth_url(
    backend_origin: str = Query("http://localhost:8000"),
    frontend_origin: str = Query("http://localhost:8080"),
):
    """生成飞书 OAuth 授权 URL"""
    app_id = get_feishu_app_id()
    if not app_id:
        return {"ok": False, "message": "飞书 App ID 未配置"}

    callback = f"{backend_origin}{CALLBACK_PATH}"
    base = _feishu_base()
    state = _create_oauth_state(frontend_origin)
    url = (
        f"{base}/open-apis/authen/v1/index"
        f"?app_id={app_id}"
        f"&redirect_uri={quote(callback, safe='')}"
        f"&state={quote(state, safe='')}"
    )
    return {"ok": True, "url": url, "callback": callback}


@router.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """接收飞书 OAuth 回调，交换 user_access_token 并存入数据库"""
    app_id = get_feishu_app_id()
    app_secret = get_feishu_app_secret()
    base = _feishu_base()
    frontend_origin = _consume_oauth_state(state)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Step 1: 获取 app_access_token
            r1 = await client.post(
                f"{base}/open-apis/auth/v3/app_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            r1.raise_for_status()
            app_token = r1.json().get("app_access_token", "")
            if not app_token:
                logger.error("OAuth: 获取 app_access_token 失败")
                return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg=获取app_token失败")

            # Step 2: 用 code 换取 user_access_token
            r2 = await client.post(
                f"{base}/open-apis/authen/v1/access_token",
                headers={"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"},
                json={"grant_type": "authorization_code", "code": code},
            )
            r2.raise_for_status()
            data = r2.json()

        if data.get("code") != 0:
            logger.error(f"OAuth token 交换失败: {data}")
            return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg={data.get('msg', '授权失败')}")

        user_data = data.get("data", {})
        access_token = user_data.get("access_token", "")
        refresh_token = user_data.get("refresh_token", "")

        if not access_token:
            return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg=未获取到用户token")

        open_id = user_data.get("open_id", "")

        # Step 3: 存入数据库
        for key, value in [
            ("feishu_user_access_token", access_token),
            ("feishu_user_refresh_token", refresh_token),
            ("feishu_user_open_id", open_id),
        ]:
            if not value:
                continue
            existing = await db.execute(select(UserConfig).where(UserConfig.key == key))
            row = existing.scalar_one_or_none()
            if row:
                row.value = value
            else:
                db.add(UserConfig(key=key, value=value))
        await db.commit()

        # Step 4: 更新内存缓存
        set_user_access_token(access_token)
        if open_id:
            from app.feishu.user_token import set_user_open_id
            set_user_open_id(open_id)
        logger.info(f"飞书用户 OAuth 授权成功，user_access_token 已保存 (open_id={open_id or '未知'})")

        return RedirectResponse(url=f"{frontend_origin}/settings?oauth=success")

    except Exception as e:
        logger.error(f"OAuth 回调异常: {e}", exc_info=True)
        return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg={str(e)[:80]}")
