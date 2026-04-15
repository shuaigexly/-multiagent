"""任务 API：提交任务、获取规划、确认执行"""
import logging
import os
import uuid
from typing import Optional

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_parser import parse_content
from app.core.event_emitter import EventEmitter
from app.core.orchestrator import orchestrate
from app.core.settings import settings
from app.core.task_planner import plan_task
from app.models.database import Task, TaskResult, get_db
from app.models.schemas import (
    TaskConfirm,
    TaskCreate,
    TaskListItem,
    TaskPlanResponse,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


@router.post("", response_model=TaskPlanResponse)
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
        os.makedirs(settings.upload_dir, exist_ok=True)
        input_file_path = os.path.join(settings.upload_dir, f"{task_id}_{file.filename}")
        async with aiofiles.open(input_file_path, "wb") as f:
            content = await file.read()
            await f.write(content)
        file_content = content.decode("utf-8", errors="replace")

    # 拼接用于规划的文本
    planning_text = input_text or ""
    if file_content:
        planning_text += f"\n\n[附件内容片段]\n{file_content[:500]}"

    # TaskPlanner 识别
    import json as _json
    ctx = _json.loads(feishu_context) if feishu_context else None
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


@router.post("/{task_id}/confirm")
async def confirm_task(
    task_id: str,
    body: TaskConfirm,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """用户确认模块选择后正式执行（BackgroundTasks 异步执行）"""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status not in ("planning", "failed"):
        raise HTTPException(400, f"任务状态 {task.status} 不允许重新确认")

    # 更新模块选择
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(status="pending", selected_modules=body.selected_modules)
    )
    await db.commit()

    background_tasks.add_task(_execute_task, task_id, body.selected_modules)
    return {"task_id": task_id, "status": "pending", "message": "任务已加入执行队列"}


@router.get("", response_model=list[TaskListItem])
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


async def _execute_task(task_id: str, selected_modules: list[str]):
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

            # 初始化 EventEmitter（Redis 可选）
            redis_client = await _get_redis()
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


async def _get_redis():
    try:
        import redis.asyncio as aioredis
        from app.core.settings import settings
        r = await aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        return r
    except Exception:
        logger.info("Redis 不可用，事件仅落库不广播")
        return None
