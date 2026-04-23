"""
工作流运行器

setup_workflow()  — 在飞书创建多维表格 App + 三张业务表，并写入初始任务
run_workflow_loop() — 持续运行调度循环，定期触发 Agent 处理 + 分析报告
stop_workflow()   — 停止循环
"""
import asyncio
import logging
from datetime import datetime

from app.bitable_workflow import bitable_ops, schema
from app.bitable_workflow.scheduler import run_one_cycle
from app.bitable_workflow.workflow_agents import AnalystAgent
from app.feishu.bitable import create_bitable, create_table

logger = logging.getLogger(__name__)

_analyst = AnalystAgent()
_running = False
analyze_lock = asyncio.Lock()  # shared with api/workflow.py to prevent concurrent reports


async def setup_workflow(name: str = "内容运营虚拟组织") -> dict:
    """
    一键初始化：
    1. 创建飞书多维表格 App
    2. 建三张表：内容任务 / 员工效能 / 周报
    3. 写入 4 条初始待选题任务

    返回 {"app_token", "url", "table_ids": {"content", "performance", "report"}}
    """
    result = await create_bitable(name)
    app_token = result["app_token"]

    content_tid = await create_table(app_token, schema.TABLE_CONTENT, schema.CONTENT_TASK_FIELDS)
    performance_tid = await create_table(app_token, schema.TABLE_PERFORMANCE, schema.PERFORMANCE_FIELDS)
    report_tid = await create_table(app_token, schema.TABLE_REPORT, schema.REPORT_FIELDS)

    for i, (title, ctype) in enumerate(schema.SEED_TASKS, 1):
        await bitable_ops.create_record(
            app_token,
            content_tid,
            {
                "标题": title,
                "内容类型": ctype,
                "状态": schema.Status.PENDING_TOPIC,
                "编辑备注": f"初始种子任务 #{i}",
            },
        )

    logger.info("Workflow setup complete: app_token=%s url=%s", app_token, result["url"])
    return {
        "app_token": app_token,
        "url": result["url"],
        "table_ids": {
            "content": content_tid,
            "performance": performance_tid,
            "report": report_tid,
        },
    }


async def run_workflow_loop(
    app_token: str,
    table_ids: dict,
    interval: int = 30,
    analysis_every: int = 5,
) -> None:
    """
    持续运行调度循环。

    每轮：
    - 调用 run_one_cycle() 处理待选题 + 待审核
    - 每 analysis_every 轮，触发 AnalystAgent 生成周报
    """
    global _running
    _running = True
    cycle = 0
    logger.info("Workflow loop started (interval=%ds, analysis_every=%d)", interval, analysis_every)

    analysis_every = max(1, analysis_every)

    while _running:
        cycle += 1
        try:
            processed = await run_one_cycle(app_token, table_ids)
            logger.info("Cycle %d: processed %d records", cycle, processed)

            if cycle % analysis_every == 0:
                period = datetime.now().strftime("%Y-%m-%d") + f" 第{cycle}轮"
                async with analyze_lock:
                    await _analyst.analyze(
                        app_token,
                        table_ids["content"],
                        table_ids["report"],
                        period,
                    )
        except Exception as exc:
            logger.error("Workflow cycle %d error: %s", cycle, exc)

        await asyncio.sleep(interval)

    logger.info("Workflow loop stopped after %d cycles", cycle)


def stop_workflow() -> None:
    global _running
    _running = False


def is_running() -> bool:
    return _running
