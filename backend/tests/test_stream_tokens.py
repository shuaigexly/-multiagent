import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi import HTTPException


def _signed_stream_token(payload: object, secret: str = "test-secret") -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"{body}.{sig}"


def test_stream_token_rejects_tamper_and_wrong_scope(monkeypatch):
    from app.core.auth import issue_stream_token, verify_stream_token
    from app.core.settings import settings

    monkeypatch.setattr(settings, "api_key", "test-secret")
    token = issue_stream_token("task-1", "task-events", ttl_seconds=60)

    verify_stream_token(token, "task-1", "task-events")
    with pytest.raises(HTTPException):
        verify_stream_token(token, "task-2", "task-events")
    with pytest.raises(HTTPException):
        verify_stream_token(token, "task-1", "workflow-stream")
    with pytest.raises(HTTPException):
        verify_stream_token(f"{token}x", "task-1", "task-events")


def test_stream_token_rejects_expired_tokens(monkeypatch):
    from app.core.auth import issue_stream_token, verify_stream_token
    from app.core.settings import settings

    monkeypatch.setattr(settings, "api_key", "test-secret")
    token = issue_stream_token("task-1", "task-events", ttl_seconds=1)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 120)

    with pytest.raises(HTTPException):
        verify_stream_token(token, "task-1", "task-events")


def test_stream_token_requires_secret_in_production(monkeypatch):
    from app.core.auth import issue_stream_token
    from app.core.settings import settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(settings, "api_key", "")

    with pytest.raises(HTTPException) as exc:
        issue_stream_token("task-1", "task-events")
    assert exc.value.status_code == 503


def test_stream_token_rejects_malformed_signed_payloads(monkeypatch):
    from app.core.auth import verify_stream_token
    from app.core.settings import settings

    monkeypatch.setattr(settings, "api_key", "test-secret")
    non_ascii_sig_body = _signed_stream_token(
        {"sub": "task-1", "purpose": "task-events"}
    ).rsplit(".", 1)[0]

    bad_tokens = [
        _signed_stream_token(["not", "an", "object"]),
        _signed_stream_token(
            {"sub": "task-1", "purpose": "task-events", "exp": "not-a-number"}
        ),
        _signed_stream_token({"sub": "task-1", "purpose": "task-events"}),
        "x" * 5000,
        ".missing-body",
        "missing-sig.",
        "\u975eascii.signature",
        f"{non_ascii_sig_body}.\u7b7e\u540d",
    ]

    for token in bad_tokens:
        with pytest.raises(HTTPException) as exc:
            verify_stream_token(token, "task-1", "task-events")
        assert exc.value.status_code == 401
