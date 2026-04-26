"""Helpers for safely fetching user supplied URLs.

LLM tools are allowed to browse public web pages, but they must not be able to
turn the backend into an SSRF client for localhost, private networks, metadata
services, or redirected internal targets.
"""
from __future__ import annotations

import ipaddress
import fnmatch
import os
import socket
from urllib.parse import urlparse

import httpx


class UnsafeURL(ValueError):
    """Raised when a URL is not safe for backend-side fetching."""


_PUBLIC_SCHEMES = {"http", "https"}


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _resolve_host(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURL("URL host could not be resolved") from exc
    ips = sorted({sockaddr[0] for *_prefix, sockaddr in infos})
    if not ips:
        raise UnsafeURL("URL host could not be resolved")
    return ips


def _allowed_host_patterns() -> list[str]:
    raw = os.getenv("PUBLIC_FETCH_ALLOWED_HOSTS") or os.getenv("FETCH_URL_ALLOWED_HOSTS") or ""
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _is_production() -> bool:
    return os.getenv("APP_ENV", os.getenv("ENV", "development")).lower() in {"prod", "production"}


def _validate_fetch_allowlist(hostname: str) -> None:
    patterns = _allowed_host_patterns()
    if not patterns:
        if _is_production():
            raise UnsafeURL("PUBLIC_FETCH_ALLOWED_HOSTS is required in production")
        return
    host = hostname.rstrip(".").lower()
    for pattern in patterns:
        if fnmatch.fnmatch(host, pattern.rstrip(".").lower()):
            return
    raise UnsafeURL("URL host is not in the public fetch allowlist")


def validate_public_http_url(url: str) -> str:
    """Validate that *url* is http(s) and resolves only to public IPs."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in _PUBLIC_SCHEMES:
        raise UnsafeURL("URL must start with http:// or https://")
    if not parsed.hostname:
        raise UnsafeURL("URL host is required")
    if parsed.username or parsed.password:
        raise UnsafeURL("URL credentials are not allowed")
    _validate_fetch_allowlist(parsed.hostname)

    try:
        if _is_blocked_ip(parsed.hostname):
            raise UnsafeURL("URL host is not public")
    except ValueError:
        for ip in _resolve_host(parsed.hostname):
            if _is_blocked_ip(ip):
                raise UnsafeURL("URL host resolves to a non-public address")

    return parsed.geturl()


async def fetch_public_url_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 15.0,
    user_agent: str = "FeishuAIBot/1.0",
    allowed_content_prefixes: tuple[str, ...] = (),
) -> tuple[bytes, httpx.Headers, str]:
    """Fetch a public URL with redirect re-validation and a hard byte cap."""
    current = validate_public_http_url(url)
    redirects_left = 3
    headers = {"User-Agent": user_agent}

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        while True:
            async with client.stream("GET", current, headers=headers) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location or redirects_left <= 0:
                        raise UnsafeURL("URL redirect is not allowed")
                    current = validate_public_http_url(str(resp.url.join(location)))
                    redirects_left -= 1
                    continue

                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "").split(";", 1)[0].lower()
                if allowed_content_prefixes and content_type:
                    if not any(content_type.startswith(prefix) for prefix in allowed_content_prefixes):
                        raise UnsafeURL(f"URL content type is not allowed: {content_type}")

                declared_size = resp.headers.get("content-length")
                if declared_size:
                    try:
                        declared_bytes = int(declared_size)
                    except ValueError:
                        raise UnsafeURL("URL response size is invalid")
                    if declared_bytes > max_bytes:
                        raise UnsafeURL("URL response is too large")

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise UnsafeURL("URL response is too large")
                    chunks.append(chunk)
                return b"".join(chunks), resp.headers, str(resp.url)
