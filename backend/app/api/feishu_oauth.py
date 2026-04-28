"""飞书 OAuth 用户授权（用于获取 user_access_token，支持任务 API 等用户级接口）"""
import logging
import os
import re
import secrets
import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.env import get_int_env
from app.core.settings import (
    get_feishu_app_id,
    get_feishu_app_secret,
    get_feishu_region,
    settings as _settings,
)
from app.core.auth import require_api_key
from app.core.observability import get_tenant_id, set_task_context
from app.core.text_utils import truncate_with_marker
from app.feishu.token_crypto import encrypt_token
from app.feishu.user_token import (
    USER_ACCESS_TOKEN_KEY,
    USER_OPEN_ID_KEY,
    USER_REFRESH_TOKEN_KEY,
    get_user_access_token,
    refresh_user_token,
    scoped_config_key,
    set_user_access_token,
    set_user_open_id,
    set_user_refresh_token,
)
from app.models.database import UserConfig, get_db

router = APIRouter(prefix="/api/v1/feishu", tags=["feishu-oauth"])
logger = logging.getLogger(__name__)

CALLBACK_PATH = "/api/v1/feishu/oauth/callback"
STATE_TTL_SECONDS = get_int_env("OAUTH_STATE_TTL_SECONDS", 600, minimum=1)
_pending_states: dict[str, tuple[str, str, float]] = {}
_USER_TOKEN_ERROR_CODES = {
    "99991663",
    "99991664",
    "99991665",
    "99991668",
    "99991671",
}


def _feishu_base() -> str:
    return "https://open.larksuite.com" if get_feishu_region() == "intl" else "https://open.feishu.cn"


def _cleanup_pending_states(now: float | None = None) -> None:
    now = now or time.time()
    expired = [
        token
        for token, (_, _, created_at) in _pending_states.items()
        if now - created_at > STATE_TTL_SECONDS
    ]
    for token in expired:
        _pending_states.pop(token, None)


def _is_allowed_origin(origin: str) -> bool:
    # v8.6.20-r10（审计 #7 安全）：除白名单匹配外，强校验 origin 必须是
    # 干净的 https://host[:port] 或 http://localhost[:port]，不允许 javascript:/
    # data:/file:/带路径/带 query/带 fragment，防 frontend_origin 注入恶意 URL
    # 然后在错误回跳时把控制权交给攻击者。
    if not origin or not isinstance(origin, str):
        return False
    try:
        from urllib.parse import urlparse
        u = urlparse(origin.rstrip("/"))
    except Exception:
        return False
    if u.scheme not in {"https", "http"}:
        return False
    if u.path not in {"", "/"} or u.query or u.fragment:
        return False
    if not u.netloc:
        return False
    allowed = [
        o.strip()
        for o in os.getenv("ALLOWED_ORIGINS", _settings.allowed_origins).split(",")
    ]
    return origin.rstrip("/") in [a.rstrip("/") for a in allowed if a]


def _is_allowed_backend_origin(origin: str) -> bool:
    allowed = [
        o.strip()
        for o in (
            _settings.allowed_backend_origins
            or _settings.public_backend_origin
            or "http://localhost:8000"
        ).split(",")
    ]
    return origin.rstrip("/") in [a.rstrip("/") for a in allowed if a]


def _hash_actor(api_key: str | None) -> str:
    """v8.6.20-r11（审计 #4）：把 API key 做 sha256 摘要绑定到 OAuth state。"""
    import hashlib as _hashlib
    if not api_key:
        return ""
    return _hashlib.sha256(api_key.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _create_oauth_state(frontend_origin: str, *, actor_hash: str = "") -> str:
    _cleanup_pending_states()
    token = secrets.token_urlsafe(16)
    tenant_id = get_tenant_id() or "default"
    # v8.6.20-r11（审计 #4 安全）：绑定 actor_hash，防 OAuth login-CSRF —— 攻击者
    # A 用 A 的 API key 调 /oauth/url 拿到 state，把登录 URL 发给受害者 B；B 同意
    # 授权后 callback 写入的 token 会被 A 在自己 tenant 名下使用。actor 绑定让
    # callback 必须由原发起人（同 API key）来消费。
    _pending_states[token] = (frontend_origin, tenant_id, time.time(), actor_hash)
    return f"{frontend_origin}|{token}"


def _consume_oauth_state(state: str, *, actor_hash: str = "") -> tuple[str, str]:
    _cleanup_pending_states()
    if "|" not in state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    frontend_origin, token = state.rsplit("|", 1)
    pending = _pending_states.pop(token, None)
    if pending is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    # v8.6.20-r12（审计 #8 安全）：之前同时接受 3-tuple/4-tuple 两种 shape，3-tuple
    # 分支默认 expected_actor="" 让 actor_hash 校验静默跳过 — 与 CSRF 防护初衷
    # 矛盾。统一只接受 4-tuple，写入侧已全部升级。
    if not isinstance(pending, tuple) or len(pending) != 4:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    expected_origin, tenant_id, created_at, expected_actor = pending
    if time.time() - created_at > STATE_TTL_SECONDS or frontend_origin != expected_origin:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    # v8.6.20-r11（审计 #4）：actor_hash 绑定校验。callback 端目前没有 require_api_key
    # 守门（飞书侧重定向无法带 X-API-Key），所以这里 expected_actor 为空时不强校验，
    # 但若 _create_oauth_state 时记录了 actor，就要求 callback 的 X-API-Key 哈希一致。
    if expected_actor and expected_actor != actor_hash:
        raise HTTPException(status_code=400, detail="OAuth state actor mismatch")
    return expected_origin, tenant_id


def _is_user_token_error(exc: Exception) -> bool:
    text = str(exc).lower()
    if any(code in text for code in _USER_TOKEN_ERROR_CODES):
        return True
    return "token" in text and any(marker in text for marker in ("expired", "expire", "invalid"))


async def _ensure_user_token() -> str:
    user_token = get_user_access_token()
    if user_token:
        return user_token
    await refresh_user_token()
    user_token = get_user_access_token()
    if not user_token:
        raise RuntimeError("missing user_access_token; please finish OAuth authorization first")
    return user_token


async def _with_user_token_retry(call):
    user_token = await _ensure_user_token()
    try:
        return await call(user_token)
    except Exception as exc:
        if not _is_user_token_error(exc):
            raise
        logger.info("user_access_token expired/invalid, refreshing and retrying once")
        await refresh_user_token()
        refreshed = await _ensure_user_token()
        return await call(refreshed)


@router.get("/oauth/status", dependencies=[Depends(require_api_key)])
async def get_oauth_status():
    """检查用户 OAuth 授权状态"""
    return {"authorized": bool(get_user_access_token())}


@router.post("/oauth/refresh", dependencies=[Depends(require_api_key)])
async def refresh_oauth_token():
    """使用服务端保存的 refresh_token 刷新用户 OAuth token"""
    try:
        await refresh_user_token()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


@router.get("/oauth/url", dependencies=[Depends(require_api_key)])
async def get_oauth_url(
    backend_origin: str | None = Query(None),
    frontend_origin: str = Query("http://localhost:5173"),
):
    """生成飞书 OAuth 授权 URL"""
    if not _is_allowed_origin(frontend_origin):
        return {"ok": False, "message": f"不允许的 frontend_origin: {frontend_origin}"}

    app_id = get_feishu_app_id()
    if not app_id:
        return {"ok": False, "message": "飞书 App ID 未配置"}

    safe_backend_origin = (backend_origin or _settings.public_backend_origin).rstrip("/")
    if not _is_allowed_backend_origin(safe_backend_origin):
        return {"ok": False, "message": f"不允许的 backend_origin: {safe_backend_origin}"}

    callback = f"{safe_backend_origin}{CALLBACK_PATH}"
    base = _feishu_base()
    # v8.6.20-r12（审计 #2 安全）：移除 v8.6.20-r11 留下的 actor_hash 死代码 —
    # 完整 OAuth login-CSRF 防护需要 session cookie 绑定，server-wide settings.api_key
    # 的 hash 对所有调用方都是相同值，达不到 per-actor 绑定效果。这里诚实地
    # 不绑 actor，未来加 session 中间件后再补回。
    state = _create_oauth_state(frontend_origin)
    url = (
        f"{base}/open-apis/authen/v1/index"
        f"?app_id={app_id}"
        f"&redirect_uri={quote(callback, safe='')}"
        f"&state={quote(state, safe='')}"
    )
    return {"ok": True, "url": url, "callback": callback}


def _scrub_oauth_msg(value: object, max_chars: int = 200) -> str:
    """v8.6.20-r10（审计 #7 安全）：剥离 control char + 截断，防止前端日志/页面渲染
    被注入。url quote 已经做 URL-safe 编码，但前端如果 unescape 后直接拼到 HTML，
    就会露出真容；此处先把不可打印字符都换成空格。"""
    s = str(value or "")
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    return s[:max_chars]


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
    frontend_origin, tenant_id = _consume_oauth_state(state)
    set_task_context(tenant_id=tenant_id)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Step 1: 获取 app_access_token
            r1 = await client.post(
                f"{base}/open-apis/auth/v3/app_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            r1.raise_for_status()
            app_token_data = r1.json()
            if app_token_data.get("code") not in (None, 0):
                logger.error("OAuth: 获取 app_access_token 失败: %s", app_token_data)
                return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg={quote(_scrub_oauth_msg(app_token_data.get('msg', '获取app_token失败')), safe='')}")
            app_token = app_token_data.get("app_access_token", "")
            if not app_token:
                logger.error("OAuth: 获取 app_access_token 失败")
                return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg={quote('获取app_token失败', safe='')}")

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
            return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg={quote(_scrub_oauth_msg(data.get('msg', '授权失败')), safe='')}")

        user_data = data.get("data", {})
        access_token = user_data.get("access_token", "")
        refresh_token = user_data.get("refresh_token", "")

        if not access_token:
            return RedirectResponse(url=f"{frontend_origin}/settings?oauth=error&msg={quote('未获取到用户token', safe='')}")

        open_id = user_data.get("open_id", "")
        encrypted_access_token = encrypt_token(access_token)
        encrypted_refresh_token = encrypt_token(refresh_token)

        # Step 3: 存入数据库
        for key, value in [
            (scoped_config_key(USER_ACCESS_TOKEN_KEY, tenant_id), encrypted_access_token),
            (scoped_config_key(USER_REFRESH_TOKEN_KEY, tenant_id), encrypted_refresh_token),
            (scoped_config_key(USER_OPEN_ID_KEY, tenant_id), open_id),
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
        set_user_access_token(access_token, tenant_id=tenant_id)
        set_user_refresh_token(refresh_token or None, tenant_id=tenant_id)
        if open_id:
            set_user_open_id(open_id, tenant_id=tenant_id)
        logger.info(f"飞书用户 OAuth 授权成功，user_access_token 已保存 (open_id={open_id or '未知'})")

        return RedirectResponse(url=f"{frontend_origin}/settings?oauth=success")

    except Exception as e:
        logger.error(f"OAuth 回调异常: {e}", exc_info=True)
        return RedirectResponse(
            url=f"{frontend_origin}/settings?oauth=error&msg={quote(_scrub_oauth_msg(truncate_with_marker(str(e), 80)), safe='')}"
        )


@router.get("/oauth/list-bases", dependencies=[Depends(require_api_key)])
async def list_user_bases_endpoint(
    folder_token: str | None = Query(None, description="optional folder token"),
):
    try:
        from app.feishu.base_picker import list_user_bases

        async def _call(user_token: str):
            return await list_user_bases(user_token, folder_token=folder_token)

        bases = await _with_user_token_retry(_call)
        return {"ok": True, "count": len(bases), "bases": bases}
    except Exception as exc:
        logger.error("list_user_bases failed: %s", exc, exc_info=True)
        return {"ok": False, "message": str(exc)}


@router.get("/oauth/list-tables", dependencies=[Depends(require_api_key)])
async def list_tables_endpoint(app_token: str = Query(..., description="bitable app_token")):
    try:
        from app.feishu.base_picker import list_tables, list_fields

        async def _call(user_token: str):
            tables = await list_tables(app_token, user_token)
            result = []
            for t in tables:
                fields = await list_fields(app_token, t["table_id"], user_token)
                result.append({
                    "table_id": t["table_id"],
                    "name": t.get("name"),
                    "fields": [
                        {
                            "field_id": f.get("field_id"),
                            "field_name": f.get("field_name"),
                            "type": f.get("type"),
                            "ui_type": f.get("ui_type"),
                            "is_primary": bool(f.get("is_primary")),
                        }
                        for f in fields
                    ],
                })
            return result

        result = await _with_user_token_retry(_call)
        return {"ok": True, "tables": result}
    except Exception as exc:
        logger.error("list_tables_endpoint failed: %s", exc, exc_info=True)
        return {"ok": False, "message": str(exc)}


@router.get("/oauth/list-dashboards", dependencies=[Depends(require_api_key)])
async def list_dashboards_endpoint(app_token: str = Query(...)):
    """v8.6.19：列出 base 已有 Dashboards。

    优先 user_access_token（走 _with_user_token_retry，过期自动 refresh 一次），
    user 不可用或失败时回退 tenant_access_token。
    """
    from app.feishu.dashboard_picker import list_dashboards
    try:
        dashboards = await _with_user_token_retry(
            lambda token: list_dashboards(app_token, user_token=token)
        )
        return {"ok": True, "dashboards": dashboards, "auth": "user"}
    except Exception as user_exc:
        logger.info("list-dashboards user_token path failed (%s), falling back to tenant", user_exc)
        try:
            dashboards = await list_dashboards(app_token, user_token=None)
            return {"ok": True, "dashboards": dashboards, "auth": "tenant"}
        except Exception as exc:
            logger.error("list-dashboards both paths failed: %s", exc, exc_info=True)
            return {"ok": False, "message": str(exc)}


@router.post("/oauth/apply-view-config", dependencies=[Depends(require_api_key)])
async def apply_view_config(app_token: str = Query(..., description="bitable app_token")):
    try:
        from app.feishu.user_token_view_setup import configure_view_groups

        async def _call(user_token: str):
            return await configure_view_groups(app_token, user_token)

        result = await _with_user_token_retry(_call)
        return {"ok": True, "applied": result["ok"], "failed": result["failed"]}
    except Exception as exc:
        logger.error("apply_view_config failed: %s", exc, exc_info=True)
        return {"ok": False, "message": str(exc)}
