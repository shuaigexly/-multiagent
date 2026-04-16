"""飞书 Bot 事件回调端点。"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from lark_oapi.core.utils import AESCipher
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.tasks import _execute_task
from app.core.settings import (
    get_feishu_bot_encrypt_key,
    get_feishu_bot_verification_token,
)
from app.core.task_planner import plan_task
from app.feishu import bot_handler
from app.models.database import AsyncSessionLocal, FeishuBotEvent, Task, TaskResult

router = APIRouter(prefix="/api/v1/feishu/bot", tags=["feishu-bot"])
logger = logging.getLogger(__name__)


def _get_bot_settings() -> dict[str, str]:
    return {
        "verification_token": get_feishu_bot_verification_token() or "",
        "encrypt_key": get_feishu_bot_encrypt_key() or "",
    }


def _verify_token(body: dict[str, Any], token: str) -> bool:
    if not token:
        return True
    header = body.get("header") or {}
    return body.get("token") == token or header.get("token") == token


def _verify_signature(request: Request, raw_body: bytes, encrypt_key: str) -> bool:
    if not encrypt_key:
        return True
    timestamp = request.headers.get("X-Lark-Request-Timestamp")
    nonce = request.headers.get("X-Lark-Request-Nonce")
    signature = request.headers.get("X-Lark-Signature")
    if not timestamp or not nonce or not signature:
        return False
    digest = hashlib.sha256((timestamp + nonce + encrypt_key).encode("utf-8") + raw_body).hexdigest()
    return hmac.compare_digest(signature, digest)


def _decode_request_body(raw_body: bytes, encrypt_key: str) -> dict[str, Any]:
    payload = json.loads(raw_body.decode("utf-8"))
    encrypted = payload.get("encrypt")
    if not encrypted:
        return payload
    if not encrypt_key:
        raise ValueError("收到加密事件，但未配置 Encrypt Key")
    plaintext = AESCipher(encrypt_key).decrypt_str(encrypted)
    return json.loads(plaintext)


@router.post("/event")
async def feishu_bot_event(request: Request, background_tasks: BackgroundTasks):
    """
    飞书事件回调入口。
    要求在 3 秒内返回 200，实际任务执行放到 BackgroundTasks。
    """
    try:
        raw_body = await request.body()
        body = _decode_request_body(raw_body, _get_bot_settings()["encrypt_key"])
        logger.info("Bot event received event_id=%s", (body.get("header") or {}).get("event_id", "unknown"))
    except Exception as exc:
        logger.warning("Bot event: 请求体解析失败: %s", exc)
        return JSONResponse({"ok": True})

    if body.get("type") == "url_verification":
        return JSONResponse({"challenge": body.get("challenge", "")})

    cfg = _get_bot_settings()
    if not _verify_signature(request, raw_body, cfg["encrypt_key"]):
        logger.warning("Bot event: 签名校验失败，已忽略")
        return JSONResponse({"ok": True})
    if not _verify_token(body, cfg["verification_token"]):
        logger.warning("Bot event: verification_token 不匹配，已忽略")
        return JSONResponse({"ok": True})

    header = body.get("header") or {}
    if header.get("event_type") != "im.message.receive_v1":
        return JSONResponse({"ok": True})

    if not bot_handler.is_valid_bot_trigger(body):
        return JSONResponse({"ok": True})

    text = bot_handler.extract_text(body)
    if not text:
        return JSONResponse({"ok": True})

    event = body.get("event") or {}
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    event_id = header.get("event_id") or str(uuid.uuid4())

    bot_event = FeishuBotEvent(
        event_id=event_id,
        source_message_id=message.get("message_id", ""),
        chat_id=message.get("chat_id"),
        open_id=(sender.get("sender_id") or {}).get("open_id"),
        status="pending",
    )
    async with AsyncSessionLocal() as db:
        db.add(bot_event)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            logger.info("Bot event 重复，已忽略: %s", event_id)
            return JSONResponse({"ok": True})

    background_tasks.add_task(
        _handle_bot_task,
        event_id=event_id,
        text=text,
        source_message_id=bot_event.source_message_id,
        chat_id=bot_event.chat_id,
        open_id=bot_event.open_id,
        redis_client=getattr(request.app.state, "redis_client", None),
    )
    return JSONResponse({"ok": True})


async def _handle_bot_task(
    event_id: str,
    text: str,
    source_message_id: str,
    chat_id: Optional[str],
    open_id: Optional[str],
    redis_client=None,
):
    task_id: Optional[str] = None
    selected_modules: list[str] = []

    try:
        await bot_handler.reply_text_in_thread(source_message_id, "正在分析，请稍候...")

        plan = await plan_task(text)
        task_id = str(uuid.uuid4())
        selected_modules = list(plan.selected_modules)
        logger.info("Bot task started event_id=%s task_id=%s modules=%s", event_id, task_id, selected_modules)

        async with AsyncSessionLocal() as db:
            task = Task(
                id=task_id,
                status="pending",
                input_text=text,
                task_type=plan.task_type,
                task_type_label=plan.task_type_label,
                selected_modules=selected_modules,
                feishu_context=None,
            )
            db.add(task)
            bot_event = await db.get(FeishuBotEvent, event_id)
            if bot_event:
                bot_event.task_id = task_id
                bot_event.status = "processing"
            await db.commit()

        await _execute_task(task_id, selected_modules, redis_client)

        async with AsyncSessionLocal() as db:
            task = await db.get(Task, task_id)
            bot_event = await db.get(FeishuBotEvent, event_id)
            result_count = await db.scalar(
                select(func.count()).select_from(TaskResult).where(TaskResult.task_id == task_id)
            )

            if not task:
                if bot_event:
                    bot_event.status = "failed"
                    bot_event.error_message = "任务不存在或已被删除"
                    await db.commit()
                await bot_handler.reply_text_in_thread(source_message_id, "分析失败：任务不存在或已被删除")
                return

            if task.status != "done":
                error_message = task.error_message or f"任务执行未成功，当前状态: {task.status}"
                if bot_event:
                    bot_event.status = "failed"
                    bot_event.error_message = error_message[:500]
                await db.commit()
                await bot_handler.reply_text_in_thread(source_message_id, f"分析失败：{error_message[:100]}")
                return

            if bot_event:
                bot_event.status = "done"
                bot_event.error_message = None
            await db.commit()

            summary = (task.result_summary or "分析完成").strip()
            frontend_base_url = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
            report_url = f"{frontend_base_url}/results/{task_id}"
            reply_text = (
                f"分析完成，共 {len(selected_modules)} 个模块参与。\n\n"
                f"{summary[:500]}\n\n"
                f"完整报告：{report_url}"
            )

        await bot_handler.reply_text_in_thread(source_message_id, reply_text)
        logger.info(
            "Bot task 完成 event_id=%s task_id=%s modules=%s results=%s chat_id=%s open_id=%s",
            event_id,
            task_id,
            selected_modules,
            result_count or 0,
            chat_id,
            open_id,
        )
    except Exception as exc:
        logger.error("Bot pipeline 执行失败 event_id=%s: %s", event_id, exc, exc_info=True)
        await bot_handler.reply_text_in_thread(source_message_id, f"分析失败：{str(exc)[:100]}")
        async with AsyncSessionLocal() as db:
            bot_event = await db.get(FeishuBotEvent, event_id)
            if bot_event:
                bot_event.status = "failed"
                bot_event.error_message = str(exc)[:500]
            if task_id:
                task = await db.get(Task, task_id)
                if task and task.status != "done":
                    task.status = "failed"
                    task.error_message = str(exc)[:500]
            await db.commit()
