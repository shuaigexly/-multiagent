"""
Orchestrator：调度 Agent 模块执行
- 并行执行非汇总型 Agent
- CEO 助理等汇总型 Agent 最后串行执行
"""
import asyncio
import logging
from typing import Optional

from app.agents.base_agent import AgentResult
from app.agents.registry import AGENT_DEPENDENCIES, AGENT_REGISTRY, SEQUENTIAL_LAST
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
    last_err = None
    for attempt in range(3):
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
            last_err = e
            if attempt < 2:
                wait = 2 ** attempt
                logger.warning(
                    f"Agent {agent_id} attempt {attempt + 1} failed: {e}. "
                    f"Retrying in {wait}s..."
                )
                await asyncio.sleep(wait)

    logger.error(f"Agent {agent_id} failed after 3 attempts: {last_err}")
    await emitter.emit_module_failed(agent.agent_id, agent.agent_name, str(last_err))
    return None


async def orchestrate(
    task_description: str,
    selected_modules: list[str],
    data_summary: Optional[DataSummary],
    feishu_context: Optional[dict],
    emitter: EventEmitter,
) -> list[AgentResult]:
    """
    Dependency-aware execution:
    1. Build a dependency graph from selected modules only
    2. Execute in waves: each wave = agents whose dependencies are already done
    3. Within a wave, run agents in parallel
    4. ceo_assistant always in the final wave (SEQUENTIAL_LAST)
    """
    selected_set = set(selected_modules)

    # Build effective deps restricted to selected modules
    dependency_prereqs: dict[str, set[str]] = {agent_id: set() for agent_id in selected_modules}
    for prerequisite, dependents in AGENT_DEPENDENCIES.items():
        if prerequisite not in selected_set:
            continue
        for dependent in dependents & selected_set:
            dependency_prereqs.setdefault(dependent, set()).add(prerequisite)

    completed: set[str] = set()
    all_results: list[AgentResult] = []
    remaining = list(selected_modules)

    while remaining:
        ready = [
            aid
            for aid in remaining
            if dependency_prereqs.get(aid, set()).issubset(completed)
            and aid not in SEQUENTIAL_LAST
        ]
        if not ready:
            ready = [
                aid
                for aid in remaining
                if dependency_prereqs.get(aid, set()).issubset(completed)
            ]

        if not ready:
            logger.warning(
                f"Dependency deadlock detected, running remaining in parallel: {remaining}"
            )
            ready = list(remaining)

        wave_tasks = [
            run_agent_safe(
                agent_id=aid,
                task_description=task_description,
                data_summary=data_summary,
                upstream_results=all_results if all_results else None,
                feishu_context=feishu_context,
                emitter=emitter,
            )
            for aid in ready
        ]
        wave_raw = await asyncio.gather(*wave_tasks, return_exceptions=True)
        wave_results = [r for r in wave_raw if isinstance(r, AgentResult)]
        all_results.extend(wave_results)
        completed.update(ready)
        remaining = [aid for aid in remaining if aid not in completed]

    if not all_results:
        raise RuntimeError("所有 Agent 模块均执行失败，任务无结果")

    return all_results
