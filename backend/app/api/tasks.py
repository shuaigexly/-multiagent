"""任务 API：提交任务、获取规划、确认执行"""
import asyncio
import logging
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.data_parser import parse_content
from app.core.env import get_int_env
from app.core.event_emitter import EventEmitter
from app.core.orchestrator import orchestrate
from app.core.settings import settings
from app.core.task_planner import plan_task
from app.core.text_utils import truncate_with_marker
from app.models.database import PublishedAsset, Task, TaskEvent, TaskResult, get_db
from app.models.schemas import (
    TaskConfirm,
    TaskCreate,
    TaskListItem,
    TaskPlanResponse,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

# Simple in-memory rate limiter: max RATE_LIMIT_MAX tasks per RATE_LIMIT_WINDOW seconds per client IP
_RATE_LIMIT_MAX = get_int_env("TASK_RATE_LIMIT_MAX", 10, minimum=1)
_RATE_LIMIT_WINDOW = get_int_env("TASK_RATE_LIMIT_WINDOW", 60, minimum=1)
_rate_limit_store: dict[str, list[float]] = defaultdict(list)
_claim_lock: asyncio.Lock | None = None
import threading as _threading
_claim_lock_init = _threading.Lock()


def _get_claim_lock() -> asyncio.Lock:
    """v8.1 修复：双检锁守护懒初始化（之前并发首次访问会创建多把锁，导致 claim 串行化失效）。"""
    global _claim_lock
    if _claim_lock is None:
        with _claim_lock_init:
            if _claim_lock is None:
                _claim_lock = asyncio.Lock()
    return _claim_lock


def _check_rate_limit(client_ip: str) -> None:
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    for ip, timestamps in list(_rate_limit_store.items()):
        fresh = [t for t in timestamps if t > window_start]
        if fresh:
            _rate_limit_store[ip] = fresh
        else:
            _rate_limit_store.pop(ip, None)
    requests = _rate_limit_store[client_ip]
    # Evict expired entries
    _rate_limit_store[client_ip] = [t for t in requests if t > window_start]
    if len(_rate_limit_store[client_ip]) >= _RATE_LIMIT_MAX:
        raise HTTPException(429, f"请求过于频繁，每 {_RATE_LIMIT_WINDOW} 秒最多创建 {_RATE_LIMIT_MAX} 个任务")
    _rate_limit_store[client_ip].append(now)


def _escape_like(value: str) -> str:
    """Escape SQLite LIKE metacharacters."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _resolve_upload_file_path(path: str | None) -> Path | None:
    if not path:
        return None
    upload_root = Path(settings.upload_dir).resolve()
    target = Path(path).resolve(strict=False)
    try:
        target.relative_to(upload_root)
    except ValueError:
        logger.warning("refusing upload file path outside upload_dir: %s", path)
        return None
    if target == upload_root:
        logger.warning("refusing upload file path pointing at upload_dir: %s", path)
        return None
    return target


async def _remove_upload_file(path: str | None) -> None:
    target = _resolve_upload_file_path(path)
    if target is None:
        return
    try:
        await asyncio.to_thread(target.unlink, missing_ok=True)
    except OSError as exc:
        logger.warning("uploaded file cleanup failed for path=%s: %s", path, exc)


@router.post("", response_model=TaskPlanResponse, dependencies=[Depends(require_api_key)])
async def create_task(
    request: Request,
    input_text: Optional[str] = Form(None),
    feishu_context: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    """
    提交任务。input_text 或 file 至少提供一个。
    返回 TaskPlanner 识别结果，用户确认后才正式执行。
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    if not input_text and not file:
        raise HTTPException(422, "input_text 或 file 至少提供一个")
    MAX_INPUT_LEN = 5000
    if input_text and len(input_text) > MAX_INPUT_LEN:
        raise HTTPException(422, f"任务描述不能超过 {MAX_INPUT_LEN} 字符")

    task_id = str(uuid.uuid4())
    input_file_path = None
    file_content = None

    # 处理上传文件
    if file:
        import pathlib

        ALLOWED_EXT = {".csv", ".txt", ".md"}
        ext = pathlib.Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(422, f"不支持的文件类型，仅接受: {', '.join(sorted(ALLOWED_EXT))}")
        MAX_SIZE = 5 * 1024 * 1024  # 5 MB
        chunks = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > MAX_SIZE:
                break
        content = bytes(chunks)
        if len(content) > MAX_SIZE:
            raise HTTPException(413, "文件大小超过 5 MB 限制")
        for _enc in ("utf-8", "gbk", "gb18030", "latin-1"):
            try:
                file_content = content.decode(_enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            raise HTTPException(422, "文件编码无法识别，请另存为 UTF-8 后重新上传")
        os.makedirs(settings.upload_dir, exist_ok=True)
        safe_name = f"{task_id}{ext}"  # never use client filename in path
        input_file_path = os.path.join(settings.upload_dir, safe_name)
        async with aiofiles.open(input_file_path, "w", encoding="utf-8") as f:
            await f.write(file_content)

    # 拼接用于规划的文本
    planning_text = input_text or ""
    if file_content:
        planning_text += f"\n\n[附件内容片段]\n{truncate_with_marker(file_content, 500)}"

    # TaskPlanner 识别
    import json as _json
    ctx = None
    if feishu_context:
        try:
            ctx = _json.loads(feishu_context)
        except _json.JSONDecodeError as exc:
            await _remove_upload_file(input_file_path)
            raise HTTPException(422, f"feishu_context JSON 格式错误: {exc}")
    try:
        plan = await plan_task(planning_text, ctx)
    except Exception:
        await _remove_upload_file(input_file_path)
        raise

    # 创建任务记录（status=planning，等待用户确认）
    task = Task(
        id=task_id,
        status="planning",
        input_text=input_text,
        input_file=input_file_path,
        task_type=plan.task_type,
        task_type_label=plan.task_type_label,
        selected_modules=plan.selected_modules,
        feishu_context=ctx,
    )
    try:
        db.add(task)
        await db.commit()
    except Exception:
        await _remove_upload_file(input_file_path)
        raise
    logger.info(
        "Task created",
        extra={"task_id": str(task.id), "task_type": task.task_type},
    )

    return TaskPlanResponse(
        task_id=task_id,
        task_type=plan.task_type,
        task_type_label=plan.task_type_label,
        selected_modules=plan.selected_modules,
        reasoning=plan.reasoning,
    )


@router.post("/{task_id}/confirm", dependencies=[Depends(require_api_key)])
async def confirm_task(
    task_id: str,
    body: TaskConfirm,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """用户确认模块选择后正式执行（BackgroundTasks 异步执行）"""
    user_instructions = (
        body.user_instructions.strip()
        if body.user_instructions and body.user_instructions.strip()
        else None
    )
    result = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status.in_(["planning", "failed"]))
        .values(
            status="pending",
            selected_modules=body.selected_modules,
            user_instructions=user_instructions,
        )
    )
    await db.commit()
    if result.rowcount == 0:
        check = await db.execute(select(Task.status).where(Task.id == task_id))
        current_status = check.scalar_one_or_none()
        if current_status is None:
            raise HTTPException(404, "任务不存在")
        raise HTTPException(400, f"任务状态 {current_status} 不允许重新确认")

    background_tasks.add_task(
        _execute_task,
        task_id,
        body.selected_modules,
        request.app.state.redis_client,
        user_instructions,
    )
    return {"task_id": task_id, "status": "pending", "message": "任务已加入执行队列"}


@router.get("", response_model=list[TaskListItem], dependencies=[Depends(require_api_key)])
async def list_tasks(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    status = (status or "").strip() or None
    search = (search or "").strip() or None
    effective_limit = limit

    query = select(Task)
    if status:
        query = query.where(Task.status == status)
    if search:
        escaped = _escape_like(search.lower())
        query = query.where(
            func.lower(func.coalesce(Task.input_text, "")).like(f"%{escaped}%", escape="\\")
        )

    result = await db.execute(
        query.order_by(Task.created_at.desc()).offset(offset).limit(effective_limit)
    )
    tasks = result.scalars().all()
    return [
        TaskListItem(
            id=t.id,
            status=t.status,
            task_type_label=t.task_type_label,
            input_text=truncate_with_marker(t.input_text, 100) if t.input_text else None,
            created_at=t.created_at,
        )
        for t in tasks
    ]


@router.get("/{task_id}/status", dependencies=[Depends(require_api_key)])
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task.status).where(Task.id == task_id))
    status = result.scalar_one_or_none()
    if status is None:
        raise HTTPException(404, "任务不存在")
    return {"status": status}


@router.delete("/{task_id}", dependencies=[Depends(require_api_key)])
async def delete_task(
    task_id: str,
    action: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if action == "cancel":
        result = await db.execute(
            update(Task)
            .where(Task.id == task_id, Task.status.in_(["planning", "pending", "running"]))
            .values(status="cancelled")
        )
        await db.commit()
        if result.rowcount == 0:
            current_status = await db.scalar(select(Task.status).where(Task.id == task_id))
            if current_status is None:
                raise HTTPException(404, "任务不存在")
            if current_status == "cancelled":
                return {"status": "cancelled"}
            raise HTTPException(400, f"任务状态 {current_status} 无法取消")
        return {"status": "cancelled"}

    task_row = await db.execute(select(Task.id, Task.input_file, Task.status).where(Task.id == task_id))
    task_data = task_row.first()
    if task_data is None:
        raise HTTPException(404, "任务不存在")

    if task_data.status in {"pending", "running"}:
        raise HTTPException(409, "task is active; cancel it before deleting")

    input_file_path = task_data.input_file

    await db.execute(delete(TaskResult).where(TaskResult.task_id == task_id))
    await db.execute(delete(TaskEvent).where(TaskEvent.task_id == task_id))
    await db.execute(delete(PublishedAsset).where(PublishedAsset.task_id == task_id))
    await db.execute(delete(Task).where(Task.id == task_id))
    await db.commit()
    await _remove_upload_file(input_file_path)
    return {"ok": True}


async def _is_task_cancelled(db: AsyncSession, task_id: str) -> bool:
    status = await db.scalar(select(Task.status).where(Task.id == task_id))
    return status == "cancelled"


async def _update_task_unless_cancelled(db: AsyncSession, task_id: str, **values) -> bool:
    result = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status != "cancelled")
        .values(**values)
    )
    await db.commit()
    return result.rowcount > 0


async def _execute_task(
    task_id: str,
    selected_modules: list[str],
    redis_client=None,
    user_instructions: Optional[str] = None,
):
    """后台执行任务（单机 MVP，无自动重试/恢复）"""
    from app.models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        emitter = None
        input_file_path = None
        try:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                return
            if task.status == "cancelled":
                return

            claim_error_message = None
            async with _get_claim_lock():
                MAX_CONCURRENT = get_int_env("MAX_CONCURRENT_TASKS", 3, minimum=1)
                running_count = await db.scalar(
                    select(func.count()).select_from(Task).where(Task.status == "running")
                )
                if (running_count or 0) >= MAX_CONCURRENT:
                    claim_error_message = f"当前运行中的任务已达上限（{MAX_CONCURRENT}），请稍后重试"
                    logger.error(
                        "Task failed",
                        extra={"task_id": task_id, "error": claim_error_message},
                    )
                    fail_result = await db.execute(
                        update(Task)
                        .where(Task.id == task_id, Task.status != "cancelled")
                        .values(status="failed", error_message=claim_error_message)
                    )
                    await db.commit()
                    if fail_result.rowcount == 0:
                        return
                else:
                    run_result = await db.execute(
                        update(Task)
                        .where(Task.id == task_id, Task.status == "pending")
                        .values(status="running")
                    )
                    await db.commit()
                    if run_result.rowcount == 0:
                        return

            if claim_error_message:
                emitter = EventEmitter(task_id=task_id, db=db, redis_client=redis_client)
                await emitter.emit_task_error(claim_error_message)
                return

            if await _is_task_cancelled(db, task_id):
                return

            await db.execute(delete(TaskResult).where(TaskResult.task_id == task_id))
            await db.execute(delete(TaskEvent).where(TaskEvent.task_id == task_id))
            await db.commit()

            # 初始化 EventEmitter（Redis 可选）
            emitter = EventEmitter(task_id=task_id, db=db, redis_client=redis_client)

            # 发布"任务开始"事件
            await emitter.emit_task_recognized(
                task.task_type or "general",
                task.task_type_label or "综合分析",
                selected_modules,
            )

            # 解析数据：优先用上传文件，其次读取飞书上下文中的文档内容
            data_summary = None
            input_file_path = task.input_file
            upload_path = _resolve_upload_file_path(input_file_path)
            if upload_path and upload_path.exists():
                async with aiofiles.open(upload_path, "r", encoding="utf-8") as f:
                    file_content = await f.read()
                data_summary = parse_content(file_content, upload_path.name)

            # 若无上传文件，则尝试从飞书上下文中读取真实文档内容
            if not data_summary and task.feishu_context:
                try:
                    data_summary = await asyncio.wait_for(
                        _enrich_from_feishu_context(task.feishu_context, emitter, task_id),
                        timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    logger.warning("飞书上下文读取超时（30s），跳过上下文增强")
                    data_summary = None
                except Exception as e:
                    logger.warning("飞书上下文读取失败: %s", e)
                    data_summary = None

            # 执行 Agent 模块
            TASK_TIMEOUT = get_int_env("TASK_TIMEOUT_SECONDS", 300, minimum=1)
            try:
                agent_results = await asyncio.wait_for(
                    orchestrate(
                        task_description=task.input_text or "",
                        selected_modules=selected_modules,
                        data_summary=data_summary,
                        feishu_context=task.feishu_context,
                        user_instructions=user_instructions or task.user_instructions,
                        emitter=emitter,
                    ),
                    timeout=TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                error_message = f"任务执行超时（超过 {TASK_TIMEOUT} 秒）"
                logger.error(
                    "Task failed",
                    extra={"task_id": task_id, "error": error_message},
                )
                if emitter is not None and not await _is_task_cancelled(db, task_id):
                    await emitter.emit_task_error(error_message)
                await _update_task_unless_cancelled(
                    db,
                    task_id,
                    status="failed",
                    error_message=error_message,
                )
                return

            if await _is_task_cancelled(db, task_id):
                return

            # 保存结果
            for ar in agent_results:
                tr = TaskResult(
                    task_id=task_id,
                    agent_id=ar.agent_id,
                    agent_name=ar.agent_name,
                    sections=[s.model_dump() for s in ar.sections],
                    action_items=ar.action_items,
                    chart_data=ar.chart_data,
                    raw_output=ar.raw_output,
                )
                db.add(tr)

            # 生成总结
            summary = ""
            for ar in agent_results:
                if ar.agent_id == "ceo_assistant" and ar.sections:
                    summary = truncate_with_marker(ar.sections[0].content or "", 500)
                    break
            if not summary and agent_results:
                summary = (
                    truncate_with_marker(agent_results[-1].sections[0].content or "", 300)
                    if agent_results[-1].sections
                    else "分析完成"
                )

            if not await _update_task_unless_cancelled(
                db,
                task_id,
                status="done",
                result_summary=summary,
            ):
                return
            try:
                await emitter.emit_task_done(summary)
            except Exception as emit_exc:
                logger.warning("task.done event emission failed: %s", emit_exc)
            await _remove_upload_file(input_file_path)

        except Exception as e:
            logger.error(
                f"Task {task_id} failed: {e}",
                exc_info=True,
                extra={"task_id": task_id, "error": str(e)},
            )
            try:
                if await _update_task_unless_cancelled(
                    db,
                    task_id,
                    status="failed",
                    error_message=str(e),
                ):
                    emitter2 = EventEmitter(task_id=task_id, db=db)
                    await emitter2.emit_task_error(str(e))
            except Exception as exc:
                logger.warning("任务失败状态更新或错误事件发送失败: %s", exc)


async def _enrich_from_feishu_context(
    feishu_context: dict,
    emitter: "EventEmitter",
    task_id: str,
) -> "DataSummary | None":
    """
    从 feishu_context 中读取真实飞书数据（文档内容 + 任务/日历摘要），
    合并为 DataSummary 供 Agent 分析使用。
    读取失败时静默降级，不中断任务。
    """
    from app.feishu.reader import read_doc_content
    from app.core.data_parser import DataSummary

    parts: list[str] = []

    # 1. 读取飞书文档（docx）内容，最多 2 篇
    drive_files = feishu_context.get("drive", [])
    doc_files = [f for f in drive_files if f.get("type") == "docx"][:2]
    for f in doc_files:
        token = f.get("token")
        name = f.get("name", "未命名文档")
        if not token:
            continue
        try:
            await emitter.emit("context.retrieved", payload={"doc_count": 0, "summary": f"正在读取飞书文档：{name}"})
            content = await read_doc_content(token)
            if content and content.strip():
                parts.append(f"【飞书文档：{name}】\n{truncate_with_marker(content, 4000)}")
                logger.info(f"[task={task_id}] 读取文档成功: {name}，{len(content)} 字")
            else:
                logger.info(f"[task={task_id}] 文档内容为空: {name}")
        except Exception as e:
            logger.warning(f"[task={task_id}] 读取文档失败({name}): {e}")

    # 2. 附加任务摘要
    tasks_list = feishu_context.get("tasks", [])
    pending_tasks = [t for t in tasks_list if not t.get("completed")]
    if pending_tasks:
        task_lines = "\n".join(
            f"- {t.get('summary', '无标题')}" + (f"（截止：{t['due']}）" if t.get("due") else "")
            for t in pending_tasks[:10]
        )
        parts.append(f"【飞书待办任务（{len(pending_tasks)} 项）】\n{task_lines}")

    # 3. 附加日历摘要
    calendar_list = feishu_context.get("calendar", [])
    if calendar_list:
        cal_lines = "\n".join(
            f"- {e.get('summary', '无标题')}" + (f"（{e.get('start_time', '')}）" if e.get("start_time") else "")
            for e in calendar_list[:10]
        )
        parts.append(f"【近期日历事项（{len(calendar_list)} 项）】\n{cal_lines}")

    if not parts:
        logger.info(f"[task={task_id}] feishu_context 中无可读取的有效数据")
        return None

    combined = "\n\n---\n\n".join(parts)
    return DataSummary(
        raw_preview=truncate_with_marker(combined, 6000),
        columns=[],
        row_count=len(parts),
        basic_stats={},
        content_type="text",
        full_text=truncate_with_marker(combined, 8000),
    )
