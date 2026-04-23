"""工作流管理 API — 初始化多维表格、启停调度循环、手动触发分析"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.bitable_workflow import bitable_ops, runner
from app.bitable_workflow.schema import Status
from app.bitable_workflow.workflow_agents import AnalystAgent

router = APIRouter(prefix="/api/v1/workflow", tags=["workflow"])
logger = logging.getLogger(__name__)

_analyst = AnalystAgent()

# 运行时状态（单进程内有效）
_state: dict = {}


class SetupRequest(BaseModel):
    name: str = "内容运营虚拟组织"


class StartRequest(BaseModel):
    app_token: str
    table_ids: dict
    interval: int = 30
    analysis_every: int = 5


class SeedRequest(BaseModel):
    app_token: str
    table_id: str
    title: str
    content_type: str = "行业洞察"


class AnalysisRequest(BaseModel):
    app_token: str
    content_table_id: str
    report_table_id: str
    period: Optional[str] = None


@router.post("/setup")
async def workflow_setup(req: SetupRequest):
    """创建飞书多维表格结构并写入初始任务。"""
    result = await runner.setup_workflow(req.name)
    _state.update(result)
    return result


@router.post("/start")
async def workflow_start(req: StartRequest, background_tasks: BackgroundTasks):
    """启动持续调度循环（后台运行）。"""
    if runner.is_running():
        raise HTTPException(status_code=400, detail="Workflow already running")
    _state.update({"app_token": req.app_token, "table_ids": req.table_ids})
    background_tasks.add_task(
        runner.run_workflow_loop,
        req.app_token,
        req.table_ids,
        req.interval,
        req.analysis_every,
    )
    return {"status": "started", "interval": req.interval, "analysis_every": req.analysis_every}


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
    """向内容任务表写入一条新的待选题任务。"""
    record_id = await bitable_ops.create_record(
        req.app_token,
        req.table_id,
        {
            "标题": req.title,
            "内容类型": req.content_type,
            "状态": Status.PENDING_TOPIC,
        },
    )
    return {"record_id": record_id}


@router.post("/analyze")
async def workflow_analyze(req: AnalysisRequest):
    """手动触发运营分析师生成周报。"""
    period = req.period or datetime.now().strftime("%Y-%m-%d 手动触发")
    report = await _analyst.analyze(
        req.app_token,
        req.content_table_id,
        req.report_table_id,
        period,
    )
    return {"status": "done", "period": period, "report_preview": report[:300]}


@router.get("/records")
async def workflow_records(app_token: str, table_id: str, status: Optional[str] = None):
    """查看多维表格中的记录（可按状态过滤）。"""
    filter_expr = f'CurrentValue.[状态]="{status}"' if status else None
    records = await bitable_ops.list_records(app_token, table_id, filter_expr=filter_expr)
    return {"count": len(records), "records": records}
