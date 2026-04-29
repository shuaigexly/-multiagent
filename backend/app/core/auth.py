import base64
import binascii
import hashlib
import hmac
import json
import os
import time
from hmac import compare_digest

from fastapi import Header, HTTPException, Request

from app.core.settings import settings


async def require_api_key(x_api_key: str = Header("", alias="X-API-Key")):
    """Simple API-key guard. Set API_KEY env var to enable; empty = dev mode (no auth)."""
    expected = settings.api_key
    env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
    if not expected and env in {"prod", "production"}:
        raise HTTPException(503, "API key is not configured")
    if expected and not compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid API key")


def _stream_secret() -> bytes:
    secret = settings.api_key
    env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
    if not secret and env in {"prod", "production"}:
        raise HTTPException(503, "API key is not configured")
    return (secret or "development-stream-secret").encode("utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _hash_audience(audience: str | None) -> str:
    """v8.6.20-r11（审计 #3）：把 client 标识（IP / UA / 二者拼接）做 sha256 摘要后存入
    payload，让 stream token 不能跨 client 重放。空 audience 退化到无绑定模式。"""
    if not audience:
        return ""
    return hashlib.sha256(audience.encode("utf-8", errors="ignore")).hexdigest()[:16]


def stream_audience_from_request(request: Request) -> str:
    """Build a stable, non-secret binding value for short-lived SSE tokens."""
    client_host = request.client.host if request.client else ""
    user_agent = (request.headers.get("user-agent") or "")[:200]
    return f"{client_host}|{user_agent}"


def issue_stream_token(subject: str, purpose: str, ttl_seconds: int = 60, *, audience: str | None = None) -> str:
    """Issue a short-lived bearer token suitable for EventSource query auth.

    v8.6.20-r11（审计 #3）：可选 audience（如 client IP）绑定，防 token 被泄漏后跨
    client 重放消费 SSE 事件。verify 端 audience 必须与签发时一致。"""
    payload: dict = {
        "sub": subject,
        "purpose": purpose,
        "exp": int(time.time()) + ttl_seconds,
    }
    aud_hash = _hash_audience(audience)
    if aud_hash:
        payload["aud"] = aud_hash
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_stream_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(sig)}"


def verify_stream_token(token: str, subject: str, purpose: str, *, audience: str | None = None) -> None:
    if not token or "." not in token or len(token) > 4096:
        raise HTTPException(401, "Invalid stream token")
    body, supplied_sig = token.rsplit(".", 1)
    if not body or not supplied_sig:
        raise HTTPException(401, "Invalid stream token")
    try:
        body_bytes = body.encode("ascii")
        supplied_sig_bytes = supplied_sig.encode("ascii")
    except UnicodeEncodeError:
        raise HTTPException(401, "Invalid stream token")
    expected_sig = _b64encode(
        hmac.new(_stream_secret(), body_bytes, hashlib.sha256).digest()
    ).encode("ascii")
    if not compare_digest(supplied_sig_bytes, expected_sig):
        raise HTTPException(401, "Invalid stream token")
    try:
        payload = json.loads(_b64decode(body))
    except (binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid stream token")
    if not isinstance(payload, dict):
        raise HTTPException(401, "Invalid stream token")
    if payload.get("sub") != subject or payload.get("purpose") != purpose:
        raise HTTPException(401, "Invalid stream token")
    # v8.6.20-r11（审计 #3）：audience 绑定校验
    aud_in_token = payload.get("aud") or ""
    aud_expected = _hash_audience(audience)
    if aud_in_token and not compare_digest(str(aud_in_token), aud_expected):
        raise HTTPException(401, "Invalid stream token")
    try:
        exp = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        raise HTTPException(401, "Invalid stream token")
    if exp < int(time.time()):
        raise HTTPException(401, "Expired stream token")
