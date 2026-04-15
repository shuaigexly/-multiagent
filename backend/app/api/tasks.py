"""任务 API：提交任务、获取规划、确认执行"""
import logging
import os
import uuid
from typing import Optional

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.data_parser import parse_content
from app.core.event_emitter import EventEmitter
from app.core.orchestrator import orchestrate
from app.core.settings import settings
from app.core.task_planner import plan_task
from app.models.database import Task, TaskEvent, TaskResult, get_db
from app.models.schemas import (
    TaskConfirm,
    TaskCreate,
    TaskListItem,
    TaskPlanResponse,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


@router.post("", response_model=TaskPlanResponse, dependencies=[Depends(require_api_key)])
async def create_task(
    input_text: Optional[str] = Form(None),
    feishu_context: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    """
    提交任务。input_text 或 file 至少提供一个。
    返回 TaskPlanner 识别结果，用户确认后才正式执行。
    """
    if not input_text and not file:
        raise HTTPException(422, "input_text 或 file 至少提供一个")

    task_id = str(uuid.uuid4())
    input_file_path = None
    file_content = None

    # 处理上传文件
    if file:
        import pathlib

        ALLOWED_EXT = {".csv", ".txt"}
        ext = pathlib.Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(422, f"不支持的文件类型，仅接受: {', '.join(ALLOWED_EXT)}")
        MAX_SIZE = 5 * 1024 * 1024  # 5 MB
        content = await file.read()
        if len(content) > MAX_SIZE:
            raise HTTPException(413, "文件大小超过 5 MB 限制")
        os.makedirs(settings.upload_dir, exist_ok=True)
        safe_name = f"{task_id}{ext}"  # never use client filename in path
        input_file_path = os.path.join(settings.upload_dir, safe_name)
        async with aiofiles.open(input_file_path, "wb") as f:
            await f.write(content)
        file_content = content.decode("utf-8", errors="replace")

    # 拼接用于规划的文本
    planning_text = input_text or ""
    if file_content:
        planning_text += f"\n\n[附件内容片段]\n{file_content[:500]}"

    # TaskPlanner 识别
    import json as _json
    ctx = None
    if feishu_context:
        try:
            ctx = _json.loads(feishu_context)
        except _json.JSONDecodeError as exc:
            raise HTTPException(422, f"feishu_context JSON 格式错误: {exc}")
    plan = await plan_task(planning_text, ctx)

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
    db.add(task)
    await db.commit()

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
    result = await db.execute(
        update(Task)
        .where(Task.id == task_id, Task.status.in_(["planning", "failed"]))
        .values(status="pending", selected_modules=body.selected_modules)
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
    )
    return {"task_id": task_id, "status": "pending", "message": "任务已加入执行队列"}


@router.get("", response_model=list[TaskListItem], dependencies=[Depends(require_api_key)])
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Task).order_by(Task.created_at.desc()).limit(50)
    )
    tasks = result.scalars().all()
    return [
        TaskListItem(
            id=t.id,
            status=t.status,
            task_type_label=t.task_type_label,
            input_text=t.input_text[:100] if t.input_text else None,
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


async def _execute_task(
    task_id: str,
    selected_modules: list[str],
    redis_client=None,
):
    """后台执行任务（单机 MVP，无自动重试/恢复）"""
    from app.models.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                return

            # 标记运行中
            await db.execute(
                update(Task).where(Task.id == task_id).values(status="running")
            )
            await db.commit()

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

            # 解析数据
            data_summary = None
            if task.input_file and os.path.exists(task.input_file):
                async with aiofiles.open(task.input_file, "r", encoding="utf-8", errors="replace") as f:
                    file_content = await f.read()
                data_summary = parse_content(file_content, os.path.basename(task.input_file))

            # 执行 Agent 模块
            agent_results = await orchestrate(
                task_description=task.input_text or "",
                selected_modules=selected_modules,
                data_summary=data_summary,
                feishu_context=task.feishu_context,
                emitter=emitter,
            )

            # 保存结果
            for ar in agent_results:
                tr = TaskResult(
                    task_id=task_id,
                    agent_id=ar.agent_id,
                    agent_name=ar.agent_name,
                    sections=[s.model_dump() for s in ar.sections],
                    action_items=ar.action_items,
                    raw_output=ar.raw_output,
                )
                db.add(tr)

            # 生成总结
            summary = ""
            for ar in agent_results:
                if ar.agent_id == "ceo_assistant" and ar.sections:
                    summary = ar.sections[0].content[:500]
                    break
            if not summary and agent_results:
                summary = agent_results[-1].sections[0].content[:300] if agent_results[-1].sections else "分析完成"

            await db.execute(
                update(Task).where(Task.id == task_id).values(
                    status="done",
                    result_summary=summary,
                )
            )
            await db.commit()
            await emitter.emit_task_done(summary)

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            try:
                await db.execute(
                    update(Task).where(Task.id == task_id).values(
                        status="failed",
                        error_message=str(e),
                    )
                )
                await db.commit()
                emitter2 = EventEmitter(task_id=task_id, db=db)
                await emitter2.emit_task_error(str(e))
            except Exception:
                pass
