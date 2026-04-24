"""Redis-backed agent result cache.

用途：当 pipeline 在 Wave 2/3 崩溃时，已完成的 Wave 1 结果不必重跑。
每个 agent 的输出以 JSON 形式缓存 2 小时；健康 Redis 不可达时静默降级（返回 None）。

KEY 格式: agent_cache:{task_id}:{agent_id}
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.agents.base_agent import AgentResult
from app.core.settings import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 2 * 60 * 60  # 2 hours
_redis_client = None
_redis_tried = False


async def _get_redis():
    """Lazy singleton Redis client; returns None if unavailable."""
    global _redis_client, _redis_tried
    if _redis_client is not None:
        return _redis_client
    if _redis_tried:
        return None  # already failed once this process lifetime
    _redis_tried = True
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis_client = client
        logger.info("Redis agent cache ready: %s", settings.redis_url)
        return client
    except Exception as exc:
        logger.info("Redis unavailable, agent cache disabled: %s", exc)
        return None


def _cache_key(task_id: str, agent_id: str) -> str:
    return f"agent_cache:{task_id}:{agent_id}"


async def get_cached_result(task_id: str, agent_id: str) -> Optional[AgentResult]:
    client = await _get_redis()
    if client is None or not task_id or not agent_id:
        return None
    try:
        payload = await client.get(_cache_key(task_id, agent_id))
        if not payload:
            return None
        return AgentResult.model_validate_json(payload)
    except Exception as exc:
        logger.debug("agent cache GET failed: %s", exc)
        return None


async def set_cached_result(task_id: str, agent_id: str, result: AgentResult) -> None:
    client = await _get_redis()
    if client is None or not task_id or not agent_id:
        return
    try:
        await client.set(
            _cache_key(task_id, agent_id),
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
        pattern = f"agent_cache:{task_id}:*"
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
