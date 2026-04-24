import asyncio
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)
_CLIENT_ERROR_PATTERN = re.compile(r"\b4(?:0[0-9]|1[0-7])\b")

_FAST_FAIL_BITABLE_CODES = (
    "1254067",  # LinkFieldConvFail
    "1254068",  # field type mismatch
    "1254043",  # field not found
)


def _is_token_expired(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "99991671" in message
        or "99991663" in message
        or ("token" in message and "expire" in message)
        or ("401" in message and "token" in message)
    )


def _is_client_error(exc: Exception) -> bool:
    message = str(exc)
    if _is_token_expired(exc):
        return False
    if any(code in message for code in _FAST_FAIL_BITABLE_CODES):
        return True
    return bool(_CLIENT_ERROR_PATTERN.search(message))


def _is_non_retryable_value_error(exc: ValueError) -> bool:
    message = str(exc)
    return any(marker in message for marker in ("未配置", "不支持", "不能为空", "缺少", "需要提供"))


async def _refresh_tokens_if_possible(exc: Exception) -> None:
    logger.warning(
        "Feishu token expired; clearing token caches before retry",
        extra={"error": str(exc)},
    )
    try:
        from app.feishu import aily

        aily._TOKEN_CACHE.clear()
    except Exception as cache_exc:
        logger.warning("Failed to clear Feishu tenant token cache: %s", cache_exc)

    try:
        from app.feishu.user_token import get_user_refresh_token, refresh_user_token

        if get_user_refresh_token():
            await refresh_user_token()
    except Exception as refresh_exc:
        logger.warning(
            "Feishu token refresh failed; falling back to normal retry flow: %s",
            refresh_exc,
        )


async def with_retry(
    func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs,
) -> Any:
    """Retry an async callable with exponential backoff."""
    last_exc: Exception = RuntimeError("no attempts made")
    refresh_attempted = False

    attempt = 0
    while attempt < max_attempts:
        try:
            return await func(*args, **kwargs)
        except ValueError as exc:
            last_exc = exc
            if _is_token_expired(exc) and not refresh_attempted:
                refresh_attempted = True
                await _refresh_tokens_if_possible(exc)
                continue
            if _is_non_retryable_value_error(exc):
                logger.debug("Configuration error, not retrying: %s", exc)
                raise
        except Exception as exc:
            last_exc = exc
            if _is_token_expired(exc) and not refresh_attempted:
                refresh_attempted = True
                await _refresh_tokens_if_possible(exc)
                continue
            if _is_client_error(exc):
                logger.warning("4xx fast-fail, not retrying", extra={"error": str(exc)})
                raise

        attempt += 1
        if attempt < max_attempts:
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Feishu call failed (attempt %s/%s): %s. Retrying in %ss",
                attempt,
                max_attempts,
                last_exc,
                delay,
                extra={"attempt": attempt, "error": str(last_exc)},
            )
            await asyncio.sleep(delay)

    raise last_exc
