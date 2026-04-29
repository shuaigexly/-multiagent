"""Sensitive value redaction helpers for logs and user-facing errors."""
from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEY_TOKENS = (
    "secret",
    "password",
    "passwd",
    "token",
    "code",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "session",
)

_KEY_VALUE_RE = re.compile(
    r"(?P<prefix>(?P<key_quote>['\"]?)\b(?:(?:[a-z0-9_-]*token)|app_secret|app-secret|api_key|api-key|"
    r"x-api-key|x_api_key|apikey|authorization|password|passwd|secret|credential|session)"
    r"\b(?P=key_quote)\s*[:=]\s*)(?P<value_quote>['\"]?)(?P<value>[^'\"\s,}\]]+)(?P=value_quote)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_FEISHU_URL_TOKEN_RE = re.compile(
    r"(?P<prefix>/(?:base|apps|permissions)/)(?P<token>[^/?#\s]+)",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@",
    re.IGNORECASE,
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?P<prefix>[?&](?:access_token|refresh_token|token|api_key|api-key|x-api-key|"
    r"authorization|password|passwd|secret|credential|session)=)(?P<value>[^&#\s]+)",
    re.IGNORECASE,
)


def is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower()
    comparable = re.sub(r"[-\s]+", "_", normalized)
    if comparable in {
        "key_field",
        "primary_key",
        "task_key",
        "cache_key",
        "code_block",
        "actor_key",
        "lookup_key",
        "status_code",
        "error_code",
        "response_code",
        "http_code",
    }:
        return False
    return any(token in comparable for token in _SENSITIVE_KEY_TOKENS)


def redact_sensitive_data(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[REDACTED:depth]"
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if is_sensitive_key(key) else redact_sensitive_data(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item, depth + 1) for item in value[:50]]
    if isinstance(value, tuple):
        return [redact_sensitive_data(item, depth + 1) for item in value[:50]]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def redact_sensitive_text(value: object, max_chars: int | None = None) -> str:
    text = str(value or "")
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _URL_USERINFO_RE.sub(lambda m: f"{m.group('scheme')}[REDACTED]@", text)
    text = _FEISHU_URL_TOKEN_RE.sub(lambda m: f"{m.group('prefix')}[REDACTED]", text)
    text = _SENSITIVE_QUERY_RE.sub(lambda m: f"{m.group('prefix')}[REDACTED]", text)
    text = _KEY_VALUE_RE.sub(
        lambda m: f"{m.group('prefix')}{m.group('value_quote')}[REDACTED]{m.group('value_quote')}",
        text,
    )
    return text[:max_chars] if max_chars is not None else text
