import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


async def with_retry(
    func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs,
) -> Any:
    """Retry an async callable with exponential backoff."""
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Feishu call failed (attempt {attempt+1}/{max_attempts}): {e}. "
                    f"Retrying in {delay}s"
                )
                await asyncio.sleep(delay)
    raise last_exc
