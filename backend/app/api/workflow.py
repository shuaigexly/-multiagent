"""工作流管理 API — 初始化多维表格、启停调度循环、手动触发分析任务 + SSE 进度流"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sse_starlette.sse import EventSourceResponse

from app.bitable_workflow import bitable_ops, progress_broker, runner
from app.bitable_workflow.schema import ALL_STATUSES, ANALYSIS_DIMENSIONS, Status
from app.core.audit import record_audit
from app.core.auth import issue_stream_token, require_api_key, verify_stream_token

_VALID_DIMENSIONS: list[str] = ANALYSIS_DIMENSIONS
_VALID_STATUSES: set[str] = set(ALL_STATUSES)

router = APIRouter(
    prefix="/api/v1/workflow",
    tags=["workflow"],
)
logger = logging.getLogger(__name__)

# 运行时状态（单进程内有效）
_state: dict = {}


class SetupRequest(BaseModel):
    name: str = "内容运营虚拟组织"


class StartRequest(BaseModel):
    app_token: str
    table_ids: dict
    interval: int = Field(default=30, ge=1)
    analysis_every: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def check_table_ids(self) -> "StartRequest":
        required = {"task", "report", "performance"}
        missing = required - self.table_ids.keys()
        if missing:
            raise ValueError(f"table_ids 缺少必需键: {missing}")
        for key, val in self.table_ids.items():
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"table_ids['{key}'] 不能为空字符串")
        return self


class SeedRequest(BaseModel):
    app_token: str
    table_id: str
    title: str = Field(min_length=1)
    dimension: str = "综合分析"
    background: str = ""

    @field_validator("dimension")
    @classmethod
    def check_dimension(cls, v: str) -> str:
        if v not in _VALID_DIMENSIONS:
            raise ValueError(f"dimension 必须是以下之一: {_VALID_DIMENSIONS}")
        return v


@router.post("/setup", dependencies=[Depends(require_api_key)])
async def workflow_setup(req: SetupRequest):
    """创建飞书多维表格结构（四张表）并写入初始分析任务。"""
    if runner.is_running():
        raise HTTPException(
            status_code=409,
            detail="Workflow loop is running; call /stop first before re-setup",
        )
    result = await runner.setup_workflow(req.name)
    _state.update(result)
    await record_audit(
        "workflow.setup",
        target=result.get("app_token", ""),
        payload={"name": req.name, "url": result.get("url", "")},
    )
    return result


@router.post("/start", dependencies=[Depends(require_api_key)])
async def workflow_start(req: StartRequest, background_tasks: BackgroundTasks):
    """启动七岗多智能体持续调度循环（后台运行）。"""
    if not runner.mark_starting():
        raise HTTPException(status_code=400, detail="Workflow already running")
    _state.update({"app_token": req.app_token, "table_ids": req.table_ids})
    background_tasks.add_task(
        runner.run_workflow_loop,
        req.app_token,
        req.table_ids,
        req.interval,
        req.analysis_every,
    )
    await record_audit(
        "workflow.start",
        target=req.app_token,
        payload={"interval": req.interval},
    )
    return {"status": "started", "interval": req.interval}


@router.post("/stop", dependencies=[Depends(require_api_key)])
async def workflow_stop():
    """停止调度循环。"""
    runner.stop_workflow()
    await record_audit("workflow.stop", target=_state.get("app_token", ""))
    return {"status": "stopped"}


@router.get("/status", dependencies=[Depends(require_api_key)])
async def workflow_status():
    """返回当前运行状态和多维表格信息。"""
    return {"running": runner.is_running(), "state": _state}


@router.post("/seed", dependencies=[Depends(require_api_key)])
async def workflow_seed(req: SeedRequest):
    """向分析任务表写入一条新的待处理任务。"""
    record_id = await bitable_ops.create_record(
        req.app_token,
        req.table_id,
        {
            "任务标题": req.title,
            "分析维度": req.dimension,
            "背景说明": req.background,
            "状态": Status.PENDING,
            "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    )
    await record_audit(
        "workflow.seed",
        target=record_id,
        payload={"title": req.title, "dimension": req.dimension, "app_token": req.app_token},
    )
    return {"record_id": record_id}


@router.post("/stream-token/{task_record_id}", dependencies=[Depends(require_api_key)])
async def workflow_stream_token(task_record_id: str):
    return {
        "token": issue_stream_token(
            subject=task_record_id,
            purpose="workflow-stream",
            ttl_seconds=60,
        )
    }


@router.get("/stream/{task_record_id}")
async def workflow_stream(
    task_record_id: str,
    request: Request,
    token: str = Query(""),
):
    """SSE 流：实时推送 Bitable 工作流的 Wave 进度事件。

    订阅后立即接收 task.started / wave.completed / task.done / task.error 等事件。
    前端使用 EventSource 即可订阅；连接保持到 task.done/task.error 或客户端断开。
    """
    verify_stream_token(token, subject=task_record_id, purpose="workflow-stream")

    async def _gen():
        async for msg in progress_broker.subscribe(task_record_id):
            if await request.is_disconnected():
                break
            yield {"event": msg["event_type"], "data": json.dumps(msg, ensure_ascii=False)}

    return EventSourceResponse(_gen(), media_type="text/event-stream")


@router.get("/records", dependencies=[Depends(require_api_key)])
async def workflow_records(app_token: str, table_id: str, status: Optional[str] = None):
    """查看多维表格中的记录（可按状态过滤）。"""
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态值，有效值为: {sorted(_VALID_STATUSES)}",
        )
    filter_expr = f"CurrentValue.[状态]={bitable_ops.quote_filter_value(status)}" if status else None
    records = await bitable_ops.list_records(app_token, table_id, filter_expr=filter_expr)
    return {"count": len(records), "records": records}
