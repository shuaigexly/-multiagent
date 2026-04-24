"""工作流管理 API — 初始化多维表格、启停调度循环、手动触发分析任务"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator

from app.bitable_workflow import bitable_ops, runner
from app.bitable_workflow.schema import ALL_STATUSES, ANALYSIS_DIMENSIONS, Status

_VALID_DIMENSIONS: list[str] = ANALYSIS_DIMENSIONS
_VALID_STATUSES: set[str] = set(ALL_STATUSES)

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])
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


@router.post("/setup")
async def workflow_setup(req: SetupRequest):
    """创建飞书多维表格结构（四张表）并写入初始分析任务。"""
    if runner.is_running():
        raise HTTPException(
            status_code=409,
            detail="Workflow loop is running; call /stop first before re-setup",
        )
    result = await runner.setup_workflow(req.name)
    _state.update(result)
    return result


@router.post("/start")
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
    return {"status": "started", "interval": req.interval}


@router.post("/stop")
async def workflow_stop():
    """停止调度循环。"""
    runner.stop_workflow()
    return {"status": "stopped"}


@router.get("/status")
async def workflow_status():
    """返回当前运行状态和多维表格信息。"""
    return {"running": runner.is_running(), "state": _state}


@router.post("/seed")
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
    return {"record_id": record_id}


@router.get("/records")
async def workflow_records(app_token: str, table_id: str, status: Optional[str] = None):
    """查看多维表格中的记录（可按状态过滤）。"""
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态值，有效值为: {sorted(_VALID_STATUSES)}",
        )
    filter_expr = f'CurrentValue.[状态]="{status}"' if status else None
    records = await bitable_ops.list_records(app_token, table_id, filter_expr=filter_expr)
    return {"count": len(records), "records": records}
