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
    r"x-api-key|x_api_key|apikey|authorization|authorization_code|oauth_code|password|passwd|secret|credential|session)"
    r"\b(?P=key_quote)\s*[:=]\s*)(?P<value_quote>['\"]?)(?P<value>[^'\"\s,}\]]+)(?P=value_quote)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_FEISHU_URL_TOKEN_RE = re.compile(
    r"(?P<prefix>/(?:base|apps|permissions|documents|spreadsheets|spaces|nodes|files|medias)/)"
    r"(?P<token>[^/?#\s]+)",
    re.IGNORECASE,
)
_FEISHU_DIRECT_URL_TOKEN_RE = re.compile(
    r"(?P<prefix>https?://[^/\s]+/(?:wiki|sheets)/)(?P<token>[^/?#\s]+)",
    re.IGNORECASE,
)
_URL_USERINFO_RE = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@",
    re.IGNORECASE,
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?P<prefix>[?&](?:access_token|refresh_token|token|api_key|api-key|x-api-key|"
    r"authorization|authorization_code|oauth_code|code|state|password|passwd|secret|credential|session)=)"
    r"(?P<value>[^&#\s]+)",
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
    if value is None or isinstance(value, (bool, int, float)):
        return value
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
    if isinstance(value, (bytes, bytearray)):
        try:
            return redact_sensitive_text(bytes(value).decode("utf-8", errors="replace"))
        except Exception:
            return "[REDACTED:bytes]"
    if isinstance(value, BaseException):
        return redact_sensitive_text(repr(value))
    # Round-10 修复 #6：dataclass / BaseModel / 任意对象 — repr 转字符串后再脱敏，
    # 避免 json.dumps(default=str) 让 token/secret 直通 sink。
    return redact_sensitive_text(repr(value))


def _redact_key_value(match: "re.Match[str]") -> str:
    # Round-10 修复 #2：跳过已脱敏的 value，避免产生 `[REDACTED]]` 二次替换尾巴。
    if match.group("value") == "[REDACTED]":
        return match.group(0)
    return (
        f"{match.group('prefix')}{match.group('value_quote')}"
        f"[REDACTED]{match.group('value_quote')}"
    )


def redact_sensitive_text(value: object, max_chars: int | None = None) -> str:
    # Round-10 修复 #5：`str(value or "")` 会把 0 / False / 空 list 抹成 ""——保留真值。
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        text = str(value)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _URL_USERINFO_RE.sub(lambda m: f"{m.group('scheme')}[REDACTED]@", text)
    text = _FEISHU_URL_TOKEN_RE.sub(lambda m: f"{m.group('prefix')}[REDACTED]", text)
    text = _FEISHU_DIRECT_URL_TOKEN_RE.sub(lambda m: f"{m.group('prefix')}[REDACTED]", text)
    text = _SENSITIVE_QUERY_RE.sub(lambda m: f"{m.group('prefix')}[REDACTED]", text)
    text = _KEY_VALUE_RE.sub(_redact_key_value, text)
    return text[:max_chars] if max_chars is not None else text
