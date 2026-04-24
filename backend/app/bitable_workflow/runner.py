"""
工作流运行器（七岗多智能体版）

setup_workflow()     — 在飞书创建多维表格 App + 四张业务表，并写入初始分析任务
run_workflow_loop()  — 持续运行调度循环，定期触发七岗 DAG 分析流水线
stop_workflow()      — 停止循环
"""
import asyncio
import logging
from typing import Optional

from app.bitable_workflow import bitable_ops, schema
from app.bitable_workflow.scheduler import run_one_cycle
from app.feishu.bitable import create_bitable, create_table

logger = logging.getLogger(__name__)

_running = False
_stop_event: Optional[asyncio.Event] = None
analyze_lock = asyncio.Lock()  # shared with api/workflow.py to prevent concurrent manual triggers


async def setup_workflow(name: str = "内容运营虚拟组织") -> dict:
    """
    一键初始化：
    1. 创建飞书多维表格 App
    2. 建四张表：分析任务 / 岗位分析 / 综合报告 / 数字员工效能
    3. 写入 4 条初始分析任务（覆盖内容战略、数据复盘、增长优化、产品规划四个维度）

    返回 {"app_token", "url", "table_ids": {"task", "output", "report", "performance"}}
    """
    result = await create_bitable(name)
    app_token = result["app_token"]

    task_tid = await create_table(app_token, schema.TABLE_TASK, schema.TASK_FIELDS)
    output_tid = await create_table(app_token, schema.TABLE_AGENT_OUTPUT, schema.AGENT_OUTPUT_FIELDS)
    report_tid = await create_table(app_token, schema.TABLE_REPORT, schema.REPORT_FIELDS)
    performance_tid = await create_table(app_token, schema.TABLE_PERFORMANCE, schema.PERFORMANCE_FIELDS)

    for title, dimension, background in schema.SEED_TASKS:
        await bitable_ops.create_record(
            app_token,
            task_tid,
            {
                "任务标题": title,
                "分析维度": dimension,
                "状态": schema.Status.PENDING,
                "背景说明": background,
            },
        )

    logger.info("Workflow setup complete: app_token=%s url=%s", app_token, result["url"])
    return {
        "app_token": app_token,
        "url": result["url"],
        "table_ids": {
            "task": task_tid,
            "output": output_tid,
            "report": report_tid,
            "performance": performance_tid,
        },
    }


def mark_starting() -> bool:
    """Atomically mark the loop as starting before the background task fires.

    Returns True if the transition succeeded (was idle), False if already running.
    Call this in the API handler immediately before scheduling the background task
    so that a second concurrent /start request sees is_running()=True and is rejected.
    """
    global _running
    if _running:
        return False
    _running = True
    return True


async def run_workflow_loop(
    app_token: str,
    table_ids: dict,
    interval: int = 30,
    analysis_every: int = 5,  # kept for API compatibility; analysis is now per-task in pipeline
) -> None:
    """
    持续运行七岗多智能体调度循环。

    每轮调用 run_one_cycle()，对所有「待分析」任务执行完整的七岗 DAG 流水线：
    Wave1（5个并行Agent）→ Wave2（财务顾问）→ Wave3（CEO助理综合）
    """
    global _running, _stop_event
    _running = True  # belt-and-suspenders; mark_starting() already set this
    _stop_event = asyncio.Event()
    cycle = 0
    logger.info("Workflow loop started (interval=%ds)", interval)

    try:
        while _running:
            cycle += 1
            try:
                processed = await run_one_cycle(app_token, table_ids)
                logger.info("Cycle %d: processed %d tasks", cycle, processed)
            except Exception as exc:
                logger.error("Workflow cycle %d error: %s", cycle, exc)

            # Interruptible sleep: wakes immediately if stop_workflow() is called
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=float(interval))
                break  # stop_event was set — exit loop without waiting full interval
            except asyncio.TimeoutError:
                pass  # normal interval elapsed, continue
    finally:
        _running = False
        _stop_event = None

    logger.info("Workflow loop stopped after %d cycles", cycle)


def stop_workflow() -> None:
    global _running
    _running = False
    if _stop_event is not None:
        _stop_event.set()


def is_running() -> bool:
    return _running
