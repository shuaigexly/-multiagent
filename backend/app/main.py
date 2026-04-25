"""FastAPI 应用入口"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
from sqlalchemy import select, update

from app.api import config as config_api
from app.api import events, feishu, feishu_bot as feishu_bot_api, feishu_context as feishu_context_api, feishu_oauth as feishu_oauth_api, results, tasks, workflow as workflow_api
from app.core.settings import apply_db_config, settings
from app.feishu.client import reset_feishu_client
from app.feishu import mcp_client
from app.feishu.token_crypto import decrypt_token
from app.models.database import AsyncSessionLocal, Task, UserConfig, init_db
from app.core.event_emitter import EventEmitter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=_sentry_dsn,
            integrations=[FastApiIntegration(), SqlalchemyIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("sentry-sdk not installed; skipping Sentry init")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化数据库
    await init_db()
    await _load_runtime_config()
    app.state.redis_client = None
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        app.state.redis_client = r
        logger.info("Redis connected")
    except Exception:
        logger.info("Redis not available, falling back to DB polling")
    # 恢复遗留任务：把 pending/running 标为 failed
    await _recover_interrupted_tasks()
    logger.info("飞书 AI 工作台启动完成")
    yield
    if app.state.redis_client:
        await app.state.redis_client.aclose()
    try:
        from app.bitable_workflow.bitable_ops import close_http_client

        await close_http_client()
    except Exception as exc:
        logger.warning("Bitable HTTP client shutdown failed: %s", exc)
    try:
        from app.feishu.bitable import close_http_client as close_feishu_bitable_http_client

        await close_feishu_bitable_http_client()
    except Exception as exc:
        logger.warning("Feishu Bitable HTTP client shutdown failed: %s", exc)
    await mcp_client.shutdown()
    logger.info("飞书 AI 工作台关闭")


async def _recover_interrupted_tasks():
    """
    启动时恢复：把上次异常退出遗留的 pending/running 任务标为 failed。
    BackgroundTasks 单机 MVP 策略，无自动重试。
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Task).where(Task.status.in_(["pending", "running"]))
        )
        stale_tasks = result.scalars().all()
        if not stale_tasks:
            return
        for task in stale_tasks:
            await db.execute(
                update(Task)
                .where(Task.id == task.id)
                .values(
                    status="failed",
                    error_message="service restarted, task interrupted",
                )
            )
            emitter = EventEmitter(task_id=task.id, db=db)
            await emitter.emit_task_error("service restarted, task interrupted")
        await db.commit()
        logger.info(f"恢复了 {len(stale_tasks)} 个遗留任务（标记为 failed）")


async def _load_runtime_config():
    from app.feishu.user_token import set_user_access_token, set_user_open_id, set_user_refresh_token
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(UserConfig))
        rows = {row.key: row.value for row in result.scalars().all()}
        apply_db_config(rows)
        # 启动时恢复用户 OAuth token
        if user_token := rows.get("feishu_user_access_token"):
            try:
                set_user_access_token(decrypt_token(user_token))
                logger.info("已从数据库恢复飞书用户 OAuth token")
            except RuntimeError as exc:
                logger.warning("飞书用户 OAuth token 未加载: %s", exc)
        if refresh_token := rows.get("feishu_user_refresh_token"):
            try:
                set_user_refresh_token(decrypt_token(refresh_token))
                logger.info("已从数据库恢复飞书用户 refresh token")
            except RuntimeError as exc:
                logger.warning("飞书用户 refresh token 未加载: %s", exc)
        if open_id := rows.get("feishu_user_open_id"):
            set_user_open_id(open_id)
            logger.info(f"已从数据库恢复飞书用户 open_id: {open_id}")
    reset_feishu_client()


app = FastAPI(
    title="飞书 AI 工作台",
    description="面向复杂任务的飞书 AI 工作台 — 自动识别任务类型，调用多 Agent 模块，结果返回飞书",
    version="1.0.0",
    lifespan=lifespan,
)


def _load_allowed_origins() -> list[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "")
    env = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower()
    if not raw and env in {"prod", "production"}:
        raise RuntimeError("ALLOWED_ORIGINS must be configured in production")
    raw = raw or "http://localhost:5173,http://localhost:8080"
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if not origins:
        raise RuntimeError("ALLOWED_ORIGINS cannot be empty")
    return origins


allowed_origins = _load_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(results.router)
app.include_router(feishu.router)
app.include_router(feishu_bot_api.router)
app.include_router(feishu_context_api.router)
app.include_router(feishu_oauth_api.router)
app.include_router(config_api.router)
app.include_router(workflow_api.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "feishu-ai-workbench"}
