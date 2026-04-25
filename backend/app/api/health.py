"""健康检查 + 就绪探针 — 用于 Kubernetes / Docker swarm 滚动更新与负载均衡剔除。

  GET /healthz  → 200 一律返回（liveness：进程是否还活着）
  GET /readyz   → 200 全部依赖就绪 / 503 任一关键依赖不可用
                 （readiness：是否应该接流量）

不依赖 require_api_key —— 监控探针本身不应受 API key 影响。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Response

from app.core.settings import settings
from app.models.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


async def _check_db() -> dict[str, Any]:
    """v8.3 修复：探针不能因 DB 锁/磁盘满而挂起，加 3s 超时。
    K8s liveness/readiness 默认 timeout 1-5s，探针卡住会让 pod 被反复重启。
    """
    start = time.monotonic()
    try:
        from sqlalchemy import text

        async def _ping() -> None:
            async with AsyncSessionLocal() as db:
                await db.execute(text("SELECT 1"))

        await asyncio.wait_for(_ping(), timeout=3.0)
        return {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "DB ping timeout (3s)"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


async def _check_redis() -> dict[str, Any]:
    start = time.monotonic()
    client = None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await asyncio.wait_for(client.ping(), timeout=2.0)
        return {"ok": True, "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "optional": True, "error": str(exc)[:200]}
    finally:
        # 关键修复：ping 超时/异常时之前不会执行 aclose → 健康探针每次失败都泄漏一个 Redis 连接
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass


async def _check_llm() -> dict[str, Any]:
    """探测 LLM provider 是否可达 — 仅检查 API key 是否配置 + base url 可解析。

    不发 chat completion 请求，避免每次健康检查烧 token。
    """
    from app.core.settings import get_llm_api_key, get_llm_base_url, get_llm_provider

    provider = get_llm_provider()
    if not get_llm_api_key():
        return {"ok": False, "error": f"LLM_API_KEY not configured (provider={provider})"}
    base = get_llm_base_url()
    if not base:
        return {"ok": False, "error": "LLM_BASE_URL not configured"}
    return {"ok": True, "provider": provider, "base_url": base}


async def _check_feishu() -> dict[str, Any]:
    """检查飞书凭据是否就绪 + tenant token 缓存命中。"""
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        return {"ok": False, "error": "FEISHU_APP_ID/FEISHU_APP_SECRET not configured"}
    return {"ok": True, "region": settings.feishu_region, "app_id": settings.feishu_app_id[:12] + "..."}


@router.get("/healthz")
async def liveness() -> dict[str, Any]:
    """Liveness：只确认 Python 进程可响应；任何依赖问题不影响这个端点。"""
    return {
        "status": "ok",
        "service": "feishu-ai-workbench",
        "version": os.getenv("APP_VERSION", "dev"),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@router.get("/readyz")
async def readiness(response: Response) -> dict[str, Any]:
    """Readiness：检查 DB / Redis / LLM / Feishu 是否就绪。

    Redis 是 optional 依赖（缺失不阻断 ready），其余三项任一 fail 返回 503。
    """
    checks = await asyncio.gather(
        _check_db(),
        _check_redis(),
        _check_llm(),
        _check_feishu(),
    )
    db, redis_status, llm, feishu = checks

    critical_ok = db.get("ok") and llm.get("ok") and feishu.get("ok")
    if not critical_ok:
        response.status_code = 503

    return {
        "ready": critical_ok,
        "checks": {
            "db": db,
            "redis": redis_status,
            "llm": llm,
            "feishu": feishu,
        },
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# 旧 /health 端点保留为 /healthz 别名，避免破坏现有部署的探针路径
@router.get("/health")
async def health_alias() -> dict[str, Any]:
    return await liveness()
