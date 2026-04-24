"""Redis-backed agent result cache.

用途：当 pipeline 在 Wave 2/3 崩溃时，已完成的 Wave 1 结果不必重跑。
每个 agent 的输出以 JSON 形式缓存 2 小时；健康 Redis 不可达时静默降级（返回 None）。

KEY 格式: agent_cache:{task_id}:{agent_id}
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Optional

from app.agents.base_agent import AgentResult
from app.core.settings import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 2 * 60 * 60  # 2 hours
_redis_client = None
_redis_retry_at = 0.0
_REDIS_RETRY_SECONDS = 60.0


async def _get_redis():
    """Lazy singleton Redis client; returns None if unavailable."""
    global _redis_client, _redis_retry_at
    if _redis_client is not None:
        return _redis_client
    now = time.monotonic()
    if now < _redis_retry_at:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis_client = client
        logger.info("Redis agent cache ready: %s", settings.redis_url)
        return client
    except Exception as exc:
        _redis_retry_at = now + _REDIS_RETRY_SECONDS
        logger.info("Redis unavailable, agent cache disabled: %s", exc)
        return None


def _task_key(task_id: str) -> str:
    return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]


def _cache_key(task_id: str, agent_id: str, input_hash: str) -> str:
    return f"agent_cache:{_task_key(task_id)}:{agent_id}:{input_hash}"


async def get_cached_result(task_id: str, agent_id: str, input_hash: str) -> Optional[AgentResult]:
    client = await _get_redis()
    if client is None or not task_id or not agent_id or not input_hash:
        return None
    try:
        payload = await client.get(_cache_key(task_id, agent_id, input_hash))
        if not payload:
            return None
        return AgentResult.model_validate_json(payload)
    except Exception as exc:
        logger.debug("agent cache GET failed: %s", exc)
        return None


async def set_cached_result(task_id: str, agent_id: str, input_hash: str, result: AgentResult) -> None:
    client = await _get_redis()
    if client is None or not task_id or not agent_id or not input_hash:
        return
    try:
        await client.set(
            _cache_key(task_id, agent_id, input_hash),
            result.model_dump_json(),
            ex=_CACHE_TTL_SECONDS,
        )
    except Exception as exc:
        logger.debug("agent cache SET failed: %s", exc)


async def invalidate_task_cache(task_id: str) -> int:
    """清除某个任务的所有 agent 缓存（任务彻底完成后调用）。"""
    client = await _get_redis()
    if client is None or not task_id:
        return 0
    try:
        pattern = f"agent_cache:{_task_key(task_id)}:*"
        deleted = 0
        async for key in client.scan_iter(match=pattern, count=100):
            await client.delete(key)
            deleted += 1
        if deleted:
            logger.info("Invalidated %d cached agents for task=%s", deleted, task_id)
        return deleted
    except Exception as exc:
        logger.debug("agent cache invalidate failed: %s", exc)
        return 0
