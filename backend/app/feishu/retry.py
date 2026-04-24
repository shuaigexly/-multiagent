import asyncio
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)
_CLIENT_ERROR_PATTERN = re.compile(r"\b4(?:0[0-9]|1[0-7])\b")


def _is_token_expired(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "99991671" in message
        or "99991663" in message
        or ("token" in message and "expire" in message)
        or ("401" in message and "token" in message)
    )


def _is_client_error(exc: Exception) -> bool:
    """Return True for 4xx client errors that should not be retried."""
    message = str(exc)
    return bool(_CLIENT_ERROR_PATTERN.search(message)) and not _is_token_expired(exc)


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
        except Exception as e:
            last_exc = e
            if _is_token_expired(e) and not refresh_attempted:
                refresh_attempted = True
                logger.warning(
                    "Feishu token expired; clearing token caches before retry",
                    extra={"error": str(e)},
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
                continue

            if _is_client_error(e):
                logger.warning(
                    "4xx fast-fail, not retrying",
                    extra={"error": str(e)},
                )
                raise

            attempt += 1
            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    f"Feishu call failed (attempt {attempt}/{max_attempts}): {e}. "
                    f"Retrying in {delay}s",
                    extra={"attempt": attempt, "error": str(e)},
                )
                await asyncio.sleep(delay)
    raise last_exc
