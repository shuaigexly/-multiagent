"""
内容运营虚拟组织 — 七岗多智能体协作流水线

复用 app.agents 注册的七个 BaseAgent，按 AGENT_DEPENDENCIES DAG 组织执行：

  Wave 1（并行，无上游依赖）
    DataAnalystAgent      数据分析师  — 指标分析、趋势洞察
    ContentManagerAgent   内容负责人  — 内容资产盘点、创作策略
    SEOAdvisorAgent       SEO增长顾问 — 关键词机会、流量增长
    ProductManagerAgent   产品经理    — 需求分析、路线图规划
    OperationsManagerAgent 运营负责人 — 执行规划、任务拆解

  Wave 2（依赖数据分析师输出）
    FinanceAdvisorAgent   财务顾问    — 收支诊断、现金流分析

  Wave 3（汇总所有上游）
    CEOAssistantAgent     CEO 助理    — 综合管理决策摘要
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from app.agents.base_agent import AgentResult, ResultSection
from app.agents.ceo_assistant import ceo_assistant_agent
from app.agents.content_manager import content_manager_agent
from app.agents.data_analyst import data_analyst_agent
from app.agents.finance_advisor import finance_advisor_agent
from app.agents.operations_manager import operations_manager_agent
from app.agents.product_manager import product_manager_agent
from app.agents.seo_advisor import seo_advisor_agent
from app.bitable_workflow import bitable_ops

logger = logging.getLogger(__name__)

# Wave 1: no upstream dependency — run in parallel
_WAVE1_AGENTS = [
    data_analyst_agent,
    content_manager_agent,
    seo_advisor_agent,
    product_manager_agent,
    operations_manager_agent,
]

# Wave 2: finance_advisor needs data_analyst output
_WAVE2_AGENTS = [finance_advisor_agent]

# Wave 3: synthesizes all upstream results
_WAVE3_AGENT = ceo_assistant_agent


def _build_task_description(fields: dict) -> str:
    title = fields.get("任务标题", "未命名任务")
    dimension = fields.get("分析维度", "综合分析")
    background = fields.get("背景说明", "")
    desc = f"任务：{title}\n分析维度：{dimension}"
    if background:
        desc += f"\n背景说明：{background}"
    return desc


def _error_result(agent_id: str, agent_name: str, exc: Exception) -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_name=agent_name,
        sections=[ResultSection(title="错误", content=f"分析失败：{exc}")],
        action_items=[],
        raw_output=str(exc),
        chart_data=[],
    )


async def _safe_analyze(
    agent,
    task_description: str,
    upstream: Optional[list[AgentResult]] = None,
) -> AgentResult:
    """Run one agent with error isolation so a single failure cannot abort the pipeline."""
    try:
        return await agent.analyze(
            task_description=task_description,
            upstream_results=upstream or [],
        )
    except Exception as exc:
        logger.error("[%s] analyze failed: %s", agent.agent_id, exc)
        return _error_result(agent.agent_id, agent.agent_name, exc)


async def run_task_pipeline(task_fields: dict) -> tuple[list[AgentResult], AgentResult]:
    """
    对单条任务执行完整的七岗多智能体分析流水线。

    波次执行顺序遵循 AGENT_DEPENDENCIES DAG：
      Wave 1 → Wave 2（财务顾问，需要数据分析师输出）→ Wave 3（CEO 助理，汇总全部）

    返回：(wave1+wave2 共六个 AgentResult, CEO 助理综合 AgentResult)
    """
    task_description = _build_task_description(task_fields)
    logger.info("Pipeline started for task: %s", task_fields.get("任务标题", "?"))

    # Wave 1: parallel execution of 5 independent agents
    wave1_coros = [_safe_analyze(agent, task_description) for agent in _WAVE1_AGENTS]
    wave1_results: list[AgentResult] = list(await asyncio.gather(*wave1_coros))
    logger.info("Wave 1 complete: %d agents", len(wave1_results))

    # Wave 2: finance_advisor uses data_analyst (index 0) as upstream
    da_result = wave1_results[0]  # data_analyst_agent is first in _WAVE1_AGENTS
    fa_result = await _safe_analyze(finance_advisor_agent, task_description, upstream=[da_result])
    wave2_results = [fa_result]
    logger.info("Wave 2 complete: finance_advisor")

    # Wave 3: ceo_assistant synthesizes all upstream conclusions
    all_upstream = wave1_results + wave2_results
    ceo_result = await _safe_analyze(_WAVE3_AGENT, task_description, upstream=all_upstream)
    logger.info("Wave 3 complete: ceo_assistant")

    return all_upstream, ceo_result


async def write_agent_outputs(
    app_token: str,
    output_table_id: str,
    task_title: str,
    results: list[AgentResult],
) -> None:
    """将各岗 AgentResult 写入「岗位分析」表。每个 Agent 写一条记录。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for result in results:
        # Use first non-error section as summary
        summary_parts = [s.content[:600] for s in result.sections if "错误" not in s.title]
        summary = summary_parts[0] if summary_parts else result.raw_output[:600]
        action_text = (
            "\n".join(f"- {a}" for a in result.action_items[:10])
            if result.action_items
            else ""
        )
        try:
            await bitable_ops.create_record(
                app_token,
                output_table_id,
                {
                    "任务标题": task_title,
                    "岗位角色": result.agent_name,
                    "分析摘要": summary[:2000],
                    "行动项": action_text[:1000],
                    "生成时间": now_str,
                },
            )
        except Exception as exc:
            logger.error("Failed to write output for agent=%s: %s", result.agent_name, exc)


async def write_ceo_report(
    app_token: str,
    report_table_id: str,
    task_title: str,
    ceo_result: AgentResult,
    participant_count: int,
) -> Optional[str]:
    """将 CEO 助理综合报告写入「综合报告」表，返回 record_id。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _find_section(keyword: str) -> str:
        for s in ceo_result.sections:
            if keyword in s.title:
                return s.content[:1000]
        return ""

    try:
        record_id = await bitable_ops.create_record(
            app_token,
            report_table_id,
            {
                "报告标题": task_title,
                "核心结论": _find_section("核心结论"),
                "重要机会": _find_section("重要机会"),
                "重要风险": _find_section("重要风险"),
                "CEO决策事项": _find_section("CEO 需决策") or _find_section("决策"),
                "管理摘要": _find_section("管理摘要") or _find_section("一段话"),
                "参与岗位数": float(participant_count),
                "生成时间": now_str,
            },
        )
        return record_id
    except Exception as exc:
        logger.error("Failed to write CEO report for task=%s: %s", task_title, exc)
        return None


async def update_performance(
    app_token: str,
    performance_table_id: str,
    results: list[AgentResult],
) -> None:
    """更新数字员工效能表的处理任务数（滚动累计）。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    for result in results:
        try:
            existing = await bitable_ops.list_records(
                app_token,
                performance_table_id,
                filter_expr=f'CurrentValue.[员工姓名]="{result.agent_name}"',
            )
            if existing:
                rid = existing[0]["record_id"]
                prev = float(existing[0].get("fields", {}).get("处理任务数", 0) or 0)
                await bitable_ops.update_record(
                    app_token,
                    performance_table_id,
                    rid,
                    {"处理任务数": prev + 1, "更新时间": now_str},
                )
            else:
                await bitable_ops.create_record(
                    app_token,
                    performance_table_id,
                    {
                        "员工姓名": result.agent_name,
                        "角色": result.agent_id,
                        "处理任务数": 1.0,
                        "更新时间": now_str,
                    },
                )
        except Exception as exc:
            logger.warning("Performance update failed for %s: %s", result.agent_name, exc)
