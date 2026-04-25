"""
工作流运行器（七岗多智能体版）

setup_workflow()     — 在飞书创建多维表格 App + 四张业务表，并写入初始分析任务
run_workflow_loop()  — 持续运行调度循环，定期触发七岗 DAG 分析流水线
stop_workflow()      — 停止循环
"""
import asyncio
import logging
import threading
from typing import Optional

from app.bitable_workflow import bitable_ops, schema
from app.bitable_workflow.schema import agent_output_fields, report_fields
from app.bitable_workflow.scheduler import run_one_cycle
from app.feishu.bitable import create_bitable, create_table, create_view

logger = logging.getLogger(__name__)

_running = False
_stop_event: Optional[asyncio.Event] = None
_state_lock = threading.Lock()


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
    # 岗位分析表和综合报告表通过关联字段（type=18）与分析任务表建立表间关系
    output_tid = await create_table(app_token, schema.TABLE_AGENT_OUTPUT, agent_output_fields(task_tid))
    report_tid = await create_table(app_token, schema.TABLE_REPORT, report_fields(task_tid))
    performance_tid = await create_table(app_token, schema.TABLE_PERFORMANCE, schema.PERFORMANCE_FIELDS)

    # 为每张表创建附加视图（看板/画册）以提升可视化效果
    # 每张表的第一个视图是默认网格视图（创建表时自动生成），这里追加额外视图
    await _create_extra_views(app_token, task_tid, output_tid, report_tid, performance_tid)

    # v8.6.2 修复：飞书新建多维表格 App 时会自动创建一张「数据表」作为默认表，
    # 用户打开 base URL 默认进的就是这张空表 → 看到一片空白以为整个 Bitable 没数据。
    # 同时各业务表里也会保留默认主字段「多行文本」（rename 没生效或 Feishu API 行为变化），
    # 看起来像一列空数据。统一在 setup 末尾把这些清理掉。
    await _cleanup_auto_created_artifacts(
        app_token,
        keep_table_ids={task_tid, output_tid, report_tid, performance_tid},
    )

    for title, dimension, background in schema.SEED_TASKS:
        await bitable_ops.create_record(
            app_token,
            task_tid,
            {
                "任务标题": title,
                "分析维度": dimension,
                "优先级": "P1 高",
                "状态": schema.Status.PENDING,
                "进度": 0,
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


async def _cleanup_auto_created_artifacts(app_token: str, keep_table_ids: set[str]) -> None:
    """删除飞书自动创建的「数据表」+ 各业务表的「多行文本」垃圾字段。

    飞书行为：
      1. 新建多维表格 App 时自动创建一张默认表（名称通常为"数据表"）
      2. 业务表创建后保留默认主字段（名称通常为"多行文本"）—— 即使 SDK rename 调用成功，
         有时也会留下这条字段（与 Feishu API 行为变化有关）

    这两类"自动产物"会让 UI 显示一堆空字段/空表，让 base URL 进去看到一片空白。
    keep_table_ids: 我们刚建的 4 张业务表 id；不在这个集合的表都视为飞书自动产物，删除。
    """
    import httpx

    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token

    base = get_feishu_open_base_url()
    try:
        token = await get_tenant_access_token()
    except Exception as exc:
        logger.warning("cleanup skipped — token fetch failed: %s", exc)
        return

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0) as http:
        # 第 1 步：列出所有表，删除非业务表（飞书自动建的「数据表」）
        try:
            r = await http.get(
                f"{base}/open-apis/bitable/v1/apps/{app_token}/tables",
                headers=headers,
            )
            tables = r.json().get("data", {}).get("items", []) or []
        except Exception as exc:
            logger.warning("cleanup tables list failed: %s", exc)
            tables = []

        for tb in tables:
            tid = tb.get("table_id")
            tname = tb.get("name", "")
            if not tid or tid in keep_table_ids:
                continue
            try:
                rd = await http.delete(
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}",
                    headers=headers,
                )
                logger.info("Cleaned up auto-created table: %s (%s) status=%s", tname, tid, rd.status_code)
            except Exception as exc:
                logger.warning("Failed to delete table %s: %s", tid, exc)

        # 第 2 步：每张业务表删除「多行文本」垃圾字段
        for tid in keep_table_ids:
            try:
                rf = await http.get(
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields",
                    headers=headers,
                )
                fields = rf.json().get("data", {}).get("items", []) or []
            except Exception as exc:
                logger.warning("cleanup fields list failed table=%s: %s", tid, exc)
                continue

            for f in fields:
                fname = f.get("field_name", "")
                fid = f.get("field_id")
                # 飞书默认主字段名是「多行文本」；如果 schema 没用到这个名字，就是垃圾字段
                if fname == "多行文本" and fid:
                    try:
                        rd = await http.delete(
                            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields/{fid}",
                            headers=headers,
                        )
                        logger.info("Cleaned up 多行文本 garbage field: table=%s field=%s status=%s",
                                    tid, fid, rd.status_code)
                    except Exception as exc:
                        logger.warning("Failed to delete 多行文本 field: %s", exc)


async def _create_extra_views(
    app_token: str,
    task_tid: str,
    output_tid: str,
    report_tid: str,
    performance_tid: str,
) -> None:
    """为四张业务表创建看板/画册视图，提升多维表格视觉可读性。

    飞书在创建看板视图时会自动选中第一个 SingleSelect 字段作为分组，
    因此 schema.py 中 SingleSelect 字段的排列顺序决定默认看板分组。
    单次视图创建失败不应阻塞整体 setup — 静默降级即可。
    """
    view_plan = [
        # 分析任务表：按 状态 看板 + 任务画册
        (task_tid, "📊 状态看板", "kanban"),
        (task_tid, "📇 任务画册", "gallery"),
        # 岗位分析表：按 岗位角色 看板 + 健康度画册
        (output_tid, "👥 岗位看板", "kanban"),
        (output_tid, "🩺 健康度画册", "gallery"),
        # 综合报告表：按 综合健康度 看板
        (report_tid, "🚦 健康度看板", "kanban"),
        # 效能表：画册浏览
        (performance_tid, "🏆 效能画册", "gallery"),
    ]
    for table_id, name, vtype in view_plan:
        try:
            await create_view(app_token, table_id, name, vtype)
        except Exception as exc:
            logger.warning("创建视图失败 table=%s name=%s: %s", table_id, name, exc)


def mark_starting() -> bool:
    """Atomically mark the loop as starting before the background task fires.

    Returns True if the transition succeeded (was idle), False if already running.
    Call this in the API handler immediately before scheduling the background task
    so that a second concurrent /start request sees is_running()=True and is rejected.
    """
    global _running
    with _state_lock:
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
    with _state_lock:
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
        with _state_lock:
            _running = False
            _stop_event = None

    logger.info("Workflow loop stopped after %d cycles", cycle)


def stop_workflow() -> None:
    global _running
    with _state_lock:
        _running = False
    if _stop_event is not None:
        _stop_event.set()


def is_running() -> bool:
    with _state_lock:
        return _running
