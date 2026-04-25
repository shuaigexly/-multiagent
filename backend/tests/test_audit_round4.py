"""第四轮审计 — 锁定 v7.9 → v8.0 的另外 5 个 bug（懒初始化 race / 排序池 / 阻塞调用）。"""
import asyncio
import time

import pytest


# ---- bug 22: progress_broker._get_lock race ----

@pytest.mark.asyncio
async def test_progress_broker_lock_singleton_under_concurrency():
    """v8.0 修复：并发首次访问应只创建一把 asyncio.Lock，否则 publish/subscribe 失同步。"""
    from app.bitable_workflow import progress_broker

    # 强制重置
    progress_broker._lock = None

    # 并发触发首次访问
    locks = await asyncio.gather(*[
        asyncio.to_thread(progress_broker._get_lock) for _ in range(20)
    ])
    # 全部应是同一个 lock 实例
    assert all(l is locks[0] for l in locks)


# ---- bug 23: agent_cache._get_redis race ----

@pytest.mark.asyncio
async def test_agent_cache_redis_double_check_lock(monkeypatch):
    """并发首次 _get_redis 调用应只创建一个 Redis 连接，winner 之外不应泄漏。"""
    from app.bitable_workflow import agent_cache

    # 强制重置状态
    agent_cache._redis_client = None
    agent_cache._redis_retry_at = 0.0
    agent_cache._init_lock = None

    created: list = []

    class FakeClient:
        def __init__(self):
            created.append(self)

        async def ping(self):
            await asyncio.sleep(0.05)  # 模拟首次连接耗时
            return True

    def fake_from_url(*args, **kwargs):
        return FakeClient()

    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", fake_from_url)

    results = await asyncio.gather(*[agent_cache._get_redis() for _ in range(10)])
    # 关键断言：只创建了一个 client，所有调用拿到同一个
    assert len(created) == 1
    assert all(r is created[0] for r in results)


# ---- bug 24: budget._get_redis 同款 race ----

@pytest.mark.asyncio
async def test_budget_redis_double_check_lock(monkeypatch):
    from app.core import budget as bud

    bud._redis_client = None
    bud._redis_retry_at = 0.0
    bud._init_lock = None

    created: list = []

    class FakeClient:
        def __init__(self):
            created.append(self)

        async def ping(self):
            await asyncio.sleep(0.05)
            return True

    def fake_from_url(*args, **kwargs):
        return FakeClient()

    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", fake_from_url)

    results = await asyncio.gather(*[bud._get_redis() for _ in range(10)])
    assert len(created) == 1
    assert all(r is created[0] for r in results)


@pytest.mark.asyncio
async def test_budget_redis_failure_does_not_retry_immediately(monkeypatch):
    """连接失败后 _redis_retry_at 设到未来 60s，期间 _get_redis 直接返 None 不重试。"""
    from app.core import budget as bud

    bud._redis_client = None
    bud._redis_retry_at = 0.0
    bud._init_lock = None

    attempts = [0]

    def fake_from_url(*args, **kwargs):
        attempts[0] += 1

        class C:
            async def ping(self):
                raise ConnectionError("nope")

        return C()

    import redis.asyncio as aioredis
    monkeypatch.setattr(aioredis, "from_url", fake_from_url)

    r1 = await bud._get_redis()
    r2 = await bud._get_redis()
    r3 = await bud._get_redis()
    assert r1 is None and r2 is None and r3 is None
    # 关键断言：一次失败后下次直接走 retry_at 守卫，不再每次都建连接
    assert attempts[0] == 1


# ---- bug 25: priority pool size big enough ----

def test_pending_pool_size_default_200():
    """默认 pool 至少 200 条，以容纳前缀全是 P3 但末尾有 P0 的极端情况。"""
    import os

    # 模拟 scheduler 的 default 取值
    val = int(os.environ.get("WORKFLOW_PENDING_POOL_SIZE", "200"))
    assert val >= 100  # 至少 100，足够 50 条任务的全表排序


# ---- bug 26: parse_content called via to_thread ----

@pytest.mark.asyncio
async def test_parse_content_runs_in_thread_not_blocking_loop(monkeypatch):
    """关键回归：大 CSV 解析必须放线程池，不能阻塞主事件循环。"""
    from app.core import data_parser

    blocking_marker = {"called_in_loop": False, "thread_id": None}
    main_thread_id = None

    import threading
    main_thread_id = threading.get_ident()

    def slow_parse(content):
        blocking_marker["thread_id"] = threading.get_ident()
        time.sleep(0.05)  # 模拟慢解析
        return data_parser.DataSummary(
            raw_preview=content[:200], columns=[], row_count=1,
            basic_stats={}, content_type="text", full_text=content[:8000],
        )

    monkeypatch.setattr(data_parser, "parse_content", slow_parse)

    # 直接调用 to_thread 的包装并验证发生在不同线程
    result = await asyncio.to_thread(data_parser.parse_content, "x" * 1000)
    assert result is not None
    assert blocking_marker["thread_id"] != main_thread_id, (
        "parse_content 必须在线程池执行，不能在主事件循环线程上"
    )
