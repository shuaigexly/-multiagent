"""Arq 后台任务队列骨架（可选启用）。

启用方式：
  1. pip install arq
  2. 设置 USE_ARQ_QUEUE=1
  3. 启动 worker：python -m arq app.core.arq_queue.WorkerSettings
  4. 调用 enqueue_workflow_cycle(app_token, table_ids) 替代 BackgroundTasks

未启用时 BackgroundTasks 路径继续工作；本模块不会被自动 import。
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)


async def workflow_cycle_job(ctx: dict, app_token: str, table_ids: dict) -> int:
    """Arq job：执行一轮 run_one_cycle。"""
    from app.bitable_workflow.scheduler import run_one_cycle
    return await run_one_cycle(app_token, table_ids)


async def enqueue_workflow_cycle(app_token: str, table_ids: dict) -> str | None:
    """把一次调度入队 Arq；未配置 Arq 时返回 None。"""
    if os.getenv("USE_ARQ_QUEUE", "").lower() not in {"1", "true", "yes"}:
        return None
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        url = settings.redis_url
        pool = await create_pool(RedisSettings.from_dsn(url))
        job = await pool.enqueue_job("workflow_cycle_job", app_token, table_ids)
        return job.job_id if job else None
    except Exception as exc:
        logger.warning("Arq enqueue failed (fallback to inline run): %s", exc)
        return None


class WorkerSettings:
    """Arq worker 配置 — 通过 `python -m arq app.core.arq_queue.WorkerSettings` 启动。"""
    functions = [workflow_cycle_job]
    max_jobs = int(os.getenv("ARQ_MAX_JOBS", "4"))
    job_timeout = int(os.getenv("ARQ_JOB_TIMEOUT", "1200"))
    keep_result = int(os.getenv("ARQ_KEEP_RESULT", "3600"))

    @staticmethod
    async def startup(ctx: dict[str, Any]) -> None:
        from app.core.observability import configure_logging

        configure_logging()
        logger.info("Arq worker started (max_jobs=%s)", WorkerSettings.max_jobs)

    @staticmethod
    async def shutdown(ctx: dict[str, Any]) -> None:
        logger.info("Arq worker shutting down")
