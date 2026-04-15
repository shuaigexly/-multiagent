"""
Orchestrator：调度 Agent 模块执行
- 并行执行非汇总型 Agent
- CEO 助理等汇总型 Agent 最后串行执行
"""
import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentResult
from app.agents.registry import AGENT_REGISTRY, SEQUENTIAL_LAST
from app.core.data_parser import DataSummary
from app.core.event_emitter import EventEmitter

logger = logging.getLogger(__name__)


async def run_agent_safe(
    agent_id: str,
    task_description: str,
    data_summary: Optional[DataSummary],
    upstream_results: Optional[list[AgentResult]],
    feishu_context: Optional[dict],
    emitter: EventEmitter,
) -> Optional[AgentResult]:
    agent = AGENT_REGISTRY.get(agent_id)
    if not agent:
        logger.warning(f"Unknown agent: {agent_id}")
        return None

    await emitter.emit_module_started(agent.agent_id, agent.agent_name)
    try:
        result = await agent.analyze(
            task_description=task_description,
            data_summary=data_summary,
            upstream_results=upstream_results,
            feishu_context=feishu_context,
        )
        summary = result.sections[0].content[:100] if result.sections else "完成"
        await emitter.emit_module_completed(agent.agent_id, agent.agent_name, summary)
        return result
    except Exception as e:
        logger.error(f"Agent {agent_id} failed: {e}")
        await emitter.emit_module_failed(agent.agent_id, agent.agent_name, str(e))
        return None


async def orchestrate(
    task_description: str,
    selected_modules: list[str],
    data_summary: Optional[DataSummary],
    feishu_context: Optional[dict],
    emitter: EventEmitter,
) -> list[AgentResult]:
    """
    执行策略：
    1. 并行执行所有非 SEQUENTIAL_LAST 的 Agent
    2. 串行执行 SEQUENTIAL_LAST（ceo_assistant 等），传入上游结果
    """
    parallel_ids = [m for m in selected_modules if m not in SEQUENTIAL_LAST]
    sequential_ids = [m for m in selected_modules if m in SEQUENTIAL_LAST]

    # 并行阶段
    parallel_tasks = [
        run_agent_safe(
            agent_id=aid,
            task_description=task_description,
            data_summary=data_summary,
            upstream_results=None,
            feishu_context=feishu_context,
            emitter=emitter,
        )
        for aid in parallel_ids
    ]
    parallel_results_raw = await asyncio.gather(*parallel_tasks, return_exceptions=True)
    parallel_results = [r for r in parallel_results_raw if isinstance(r, AgentResult)]

    # 串行汇总阶段
    all_results = list(parallel_results)
    for aid in sequential_ids:
        result = await run_agent_safe(
            agent_id=aid,
            task_description=task_description,
            data_summary=data_summary,
            upstream_results=parallel_results,
            feishu_context=feishu_context,
            emitter=emitter,
        )
        if result:
            all_results.append(result)

    if not all_results:
        raise RuntimeError("所有 Agent 模块均执行失败，任务无结果")

    return all_results
