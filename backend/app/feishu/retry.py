import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _is_token_expired(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "99991671" in message
        or "99991663" in message
        or ("token" in message and "expire" in message)
        or ("401" in message and "token" in message)
    )


def _is_client_error(exc: Exception) -> bool:
    message = str(exc).strip().lower()
    return message.startswith(("400", "401", "403", "404"))


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

    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if _is_token_expired(e) and not refresh_attempted:
                refresh_attempted = True
                try:
                    from app.feishu.user_token import refresh_user_token

                    logger.warning("Feishu token expired; refreshing user token before retry")
                    await refresh_user_token()
                    continue
                except Exception as refresh_exc:
                    logger.warning(
                        "Feishu token refresh failed; falling back to normal retry flow: %s",
                        refresh_exc,
                    )

            if _is_client_error(e):
                raise

            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Feishu call failed (attempt {attempt+1}/{max_attempts}): {e}. "
                    f"Retrying in {delay}s"
                )
                await asyncio.sleep(delay)
    raise last_exc
