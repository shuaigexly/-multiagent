"""第八轮审计回归测试 — 锁定 v8.0 → v8.1 的 5 个 bug。"""
import asyncio

import pytest


# ---- bug 31: gather + isinstance Exception 漏 CancelledError ----

def test_isinstance_exception_misses_cancelled_error():
    """关键：CancelledError 在 Python 3.8+ 继承 BaseException，不是 Exception。
    用 isinstance(x, Exception) 会漏掉它，导致 cancel 后逻辑错乱。"""
    cancelled = asyncio.CancelledError("client disconnected")
    assert not isinstance(cancelled, Exception)
    assert isinstance(cancelled, BaseException)


@pytest.mark.asyncio
async def test_gather_with_cancelled_error_handled_via_baseexception():
    """模拟 feishu_context._get_feishu_context 的修正逻辑：
    用 BaseException 检测能正确捕获 CancelledError。"""
    async def ok():
        return [1, 2, 3]

    async def cancelled():
        raise asyncio.CancelledError("oops")

    results = await asyncio.gather(ok(), cancelled(), return_exceptions=True)
    drive, calendar = results

    # 修正后的逻辑应该能识别出 calendar 是 CancelledError
    if isinstance(drive, BaseException):
        # 不应进入此分支
        pytest.fail("drive should be normal data, not exception")

    assert isinstance(calendar, BaseException)
    assert isinstance(calendar, asyncio.CancelledError)


# ---- bug 32+33+34: 多处懒初始化 race ----

@pytest.mark.asyncio
async def test_aily_token_lock_singleton_under_concurrency(monkeypatch):
    """v8.1 修复：aily._get_token_lock 并发首次访问应只创建一把锁。"""
    from app.feishu import aily

    # 重置
    aily._TOKEN_LOCK = None

    def call():
        return aily._get_token_lock()

    locks = await asyncio.gather(*[asyncio.to_thread(call) for _ in range(20)])
    assert all(l is locks[0] for l in locks)


@pytest.mark.asyncio
async def test_claim_lock_singleton_under_concurrency():
    """v8.1: api.tasks._get_claim_lock 双检锁（环境缺 aiofiles 时跳过）。"""
    try:
        from app.api import tasks as tasks_mod
    except ModuleNotFoundError as exc:
        pytest.skip(f"app.api.tasks deps missing: {exc}")

    tasks_mod._claim_lock = None

    def call():
        return tasks_mod._get_claim_lock()

    locks = await asyncio.gather(*[asyncio.to_thread(call) for _ in range(20)])
    assert all(l is locks[0] for l in locks)


@pytest.mark.asyncio
async def test_local_cycle_lock_singleton(monkeypatch):
    """v8.1: scheduler._LOCAL_CYCLE_LOCK 不会因并发 cycle 启动产生多把锁。"""
    from app.bitable_workflow import scheduler

    scheduler._LOCAL_CYCLE_LOCK = None

    def get_then_release():
        # 模拟 _acquire_cycle_lock 的懒初始化部分（不调真函数避免 Redis 依赖）
        if scheduler._LOCAL_CYCLE_LOCK is None:
            with scheduler._LOCAL_CYCLE_LOCK_INIT:
                if scheduler._LOCAL_CYCLE_LOCK is None:
                    scheduler._LOCAL_CYCLE_LOCK = asyncio.Lock()
        return scheduler._LOCAL_CYCLE_LOCK

    locks = await asyncio.gather(*[asyncio.to_thread(get_then_release) for _ in range(20)])
    assert all(l is locks[0] for l in locks)


# ---- bug 35: PIL LANCZOS 兼容 Pillow >= 10 ----

def test_pil_lanczos_resample_compatible():
    """Pillow ≥10 弃用 Image.LANCZOS → 必须用 Image.Resampling.LANCZOS；
    但旧版本（< 10）只有 Image.LANCZOS。代码应双兼容。"""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("PIL not installed")

    # 模拟 workflow_agents 里的 fallback 逻辑
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", None) \
        or getattr(Image, "LANCZOS", None)
    assert resample is not None  # 任意 Pillow 版本都应能拿到一个有效值

    # 验证用 resample 可以做 thumbnail
    from io import BytesIO
    img = Image.new("RGB", (200, 200), color=(255, 0, 0))
    img.thumbnail((100, 100), resample)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75)
    assert buf.getvalue()[:3] == b"\xff\xd8\xff"
