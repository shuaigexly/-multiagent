import base64
import hashlib
import hmac
import json
import os
import time
from hmac import compare_digest

from fastapi import Header, HTTPException

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


def issue_stream_token(subject: str, purpose: str, ttl_seconds: int = 60) -> str:
    """Issue a short-lived bearer token suitable for EventSource query auth."""
    payload = {
        "sub": subject,
        "purpose": purpose,
        "exp": int(time.time()) + ttl_seconds,
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_stream_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(sig)}"


def verify_stream_token(token: str, subject: str, purpose: str) -> None:
    if not token or "." not in token:
        raise HTTPException(401, "Invalid stream token")
    body, supplied_sig = token.rsplit(".", 1)
    expected_sig = _b64encode(
        hmac.new(_stream_secret(), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not compare_digest(supplied_sig, expected_sig):
        raise HTTPException(401, "Invalid stream token")
    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(401, "Invalid stream token")
    if payload.get("sub") != subject or payload.get("purpose") != purpose:
        raise HTTPException(401, "Invalid stream token")
    if int(payload.get("exp") or 0) < int(time.time()):
        raise HTTPException(401, "Expired stream token")
