"""LLM 成本管控：按租户/任务级别 token 预算 + 超额熔断。

预算来源（优先级从高到低）：
  1. 显式参数（per_task_token_budget）
  2. 当前租户的覆盖配置（_db_overrides）
  3. settings.daily_token_budget / settings.per_task_token_budget

存储后端：
  - Redis 可用：HINCRBY 累加器，按 day/hour 自动归零（TTL）
  - Redis 不可用：进程内 dict + asyncio.Lock，进程重启后丢失

集成位置：
  - llm_client.call_llm 在每次调用后调用 record_usage(prompt_tokens, completion_tokens)
  - 调用前 check_budget() 抛 BudgetExceeded → 调用方决定降级（跳过 reflection / 简化 prompt）
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.core.observability import get_task_id, get_tenant_id
from app.core.settings import settings

logger = logging.getLogger(__name__)


class BudgetExceeded(RuntimeError):
    """LLM 调用超出预算 — 调用方应捕获并降级（如关闭 reflection、缩短 prompt）。"""


@dataclass
class BudgetStatus:
    scope: str          # "task" | "tenant" | "global"
    used: int
    limit: int
    period: str         # "day" | "task"

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        return self.used >= self.limit


class _InMemoryBudget:
    """Fallback：进程内累加器，按 day key 归档。"""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def incr(self, key: str, amount: int) -> int:
        async with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount
            return self._counters[key]

    async def get(self, key: str) -> int:
        return self._counters.get(key, 0)


_in_memory = _InMemoryBudget()
_redis_client = None
_redis_retry_at = 0.0
_REDIS_RETRY_SECONDS = 60.0
_init_lock: asyncio.Lock | None = None
import threading as _threading
_init_lock_create = _threading.Lock()


def _get_init_lock() -> asyncio.Lock:
    """v8.3 修复 meta-race：之前 _get_init_lock 自身仍是单检懒 init → 仍可能 race。"""
    global _init_lock
    if _init_lock is None:
        with _init_lock_create:
            if _init_lock is None:
                _init_lock = asyncio.Lock()
    return _init_lock


async def _get_redis():
    """v8.0 修复：双检锁防止并发首次访问产生多个 Redis 连接（winner 之外都会泄漏）。"""
    global _redis_client, _redis_retry_at
    if _redis_client is not None:
        return _redis_client
    now = time.monotonic()
    if now < _redis_retry_at:
        return None
    async with _get_init_lock():
        if _redis_client is not None:
            return _redis_client
        if time.monotonic() < _redis_retry_at:
            return None
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _redis_client = client
            return client
        except Exception as exc:
            _redis_retry_at = time.monotonic() + _REDIS_RETRY_SECONDS
            logger.debug("Budget Redis unavailable: %s", exc)
            return None


def _day_key() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _key_daily(scope: str, ident: str) -> str:
    return f"llm-budget:daily:{scope}:{ident}:{_day_key()}"


def _key_task(task_id: str) -> str:
    return f"llm-budget:task:{task_id}"


async def _incr(key: str, amount: int, ttl_seconds: int) -> int:
    client = await _get_redis()
    if client is None:
        return await _in_memory.incr(key, amount)
    try:
        new_val = await client.incrby(key, amount)
        # 第一次 incr 时设 TTL；后续 incr 不重置 TTL（避免无限延长）
        if new_val == amount:
            await client.expire(key, ttl_seconds)
        return int(new_val)
    except Exception as exc:
        logger.debug("Budget Redis INCR fallback: %s", exc)
        return await _in_memory.incr(key, amount)


async def _get(key: str) -> int:
    client = await _get_redis()
    if client is None:
        return await _in_memory.get(key)
    try:
        val = await client.get(key)
        return int(val) if val is not None else 0
    except Exception:
        return await _in_memory.get(key)


async def record_usage(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    reasoning_tokens: int = 0,
) -> int:
    """记录一次 LLM 调用消耗，返回当前任务累计。

    v8.6.18：reasoning_tokens 单独记账。火山方舟豆包等 reasoning model 在
    completion_tokens_details.reasoning_tokens 里返回，之前 record_usage 接口
    没暴露这个维度 → 计费时分不清"输出"和"推理"成本（推理 tokens 通常按
    completion 单价的 1-3 倍计费）。新增可观测性维度：
      - 任务级 reasoning 累计 key
      - 租户级日 reasoning 累计 key
      - 全局日 reasoning 累计 key
    向后兼容：reasoning_tokens 默认 0，老 caller 无需改动。

    自动从 ContextVar 读取 task_id / tenant_id，并写入：
      - 任务级累计（key TTL 24h）
      - 租户级日累计（key TTL 36h）
      - 全局日累计（key TTL 36h，用于运维大盘）
    """
    total = prompt_tokens + completion_tokens
    if total <= 0:
        return 0

    task_id = get_task_id()
    tenant_id = get_tenant_id() or "default"
    task_total = 0

    if task_id:
        task_total = await _incr(_key_task(task_id), total, ttl_seconds=24 * 3600)
        if reasoning_tokens > 0:
            await _incr(_key_task(task_id) + ":reasoning", reasoning_tokens, ttl_seconds=24 * 3600)

    await _incr(_key_daily("tenant", tenant_id), total, ttl_seconds=36 * 3600)
    await _incr(_key_daily("global", "all"), total, ttl_seconds=36 * 3600)
    if reasoning_tokens > 0:
        await _incr(_key_daily("tenant", tenant_id) + ":reasoning", reasoning_tokens, ttl_seconds=36 * 3600)
        await _incr(_key_daily("global", "all") + ":reasoning", reasoning_tokens, ttl_seconds=36 * 3600)

    return task_total


async def check_budget(strict: bool = False) -> Optional[BudgetStatus]:
    """检查当前任务/租户是否已超预算。

    strict=True 时超额抛 BudgetExceeded，否则只返回 status 供调用方判断。
    返回最早触达限额的 status（task 优先于 tenant）。
    """
    per_task_limit = settings.per_task_token_budget
    daily_limit = settings.daily_token_budget

    task_id = get_task_id()
    tenant_id = get_tenant_id() or "default"

    if task_id and per_task_limit > 0:
        used = await _get(_key_task(task_id))
        status = BudgetStatus(scope="task", used=used, limit=per_task_limit, period="task")
        if status.exceeded:
            if strict:
                raise BudgetExceeded(
                    f"task {task_id} used {used}/{per_task_limit} tokens — refusing further calls"
                )
            return status

    if daily_limit > 0:
        used = await _get(_key_daily("tenant", tenant_id))
        status = BudgetStatus(scope="tenant", used=used, limit=daily_limit, period="day")
        if status.exceeded:
            if strict:
                raise BudgetExceeded(
                    f"tenant {tenant_id} used {used}/{daily_limit} tokens today — refusing further calls"
                )
            return status

    return None


async def get_status() -> dict:
    """返回当前 task + tenant + global 三个维度用量，便于 /readyz / 监控面板查看。"""
    task_id = get_task_id()
    tenant_id = get_tenant_id() or "default"
    out: dict[str, dict] = {}
    if task_id:
        out["task"] = {
            "id": task_id,
            "used": await _get(_key_task(task_id)),
            "limit": settings.per_task_token_budget,
        }
    out["tenant_today"] = {
        "id": tenant_id,
        "used": await _get(_key_daily("tenant", tenant_id)),
        "limit": settings.daily_token_budget,
    }
    out["global_today"] = {
        "used": await _get(_key_daily("global", "all")),
    }
    return out
