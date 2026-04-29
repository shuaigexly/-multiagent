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
    r"(?P<prefix>\b(?:access_token|refresh_token|app_access_token|tenant_access_token|"
    r"app_secret|api_key|api-key|x-api-key|x_api_key|apikey|authorization|password|"
    r"passwd|secret|credential|session)"
    r"\b\s*[:=]\s*)(?P<quote>['\"]?)(?P<value>[^'\"\s,}\]]+)(?P=quote)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)


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
    text = _KEY_VALUE_RE.sub(lambda m: f"{m.group('prefix')}{m.group('quote')}[REDACTED]{m.group('quote')}", text)
    return text[:max_chars] if max_chars is not None else text
