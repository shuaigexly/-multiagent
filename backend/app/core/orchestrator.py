"""
Orchestrator：调度 Agent 模块执行
- 并行执行非汇总型 Agent
- CEO 助理等汇总型 Agent 最后串行执行
"""
import asyncio
import logging
from typing import Optional

from app.agents.base_agent import AgentResult, ResultSection
from app.agents.registry import AGENT_DEPENDENCIES, AGENT_REGISTRY, SEQUENTIAL_LAST
from app.core.data_parser import DataSummary
from app.core.event_emitter import EventEmitter

logger = logging.getLogger(__name__)


def _assess_data_availability(
    data_summary: Optional[DataSummary],
    feishu_context: Optional[dict],
) -> tuple[bool, str]:
    """
    Returns (can_proceed, message).
    can_proceed=False means no analyzable data exists.
    """
    # Check uploaded file data
    if data_summary is not None:
        return True, ""

    # Check feishu context
    if feishu_context:
        drive = feishu_context.get("drive") or []
        tasks = feishu_context.get("tasks") or []
        calendar = feishu_context.get("calendar") or []
        if drive or tasks or calendar:
            return True, ""

    # No data at all
    message = (
        "暂无可分析的数据，无法启动智能分析。\n\n"
        "请提供以下任意一项后重试：\n"
        "• 上传数据文件（.csv / .txt / .md）\n"
        "• 在飞书设置中选择关联的云文档或电子表格\n"
        "• 关联飞书任务清单或近期日历事项\n\n"
        "数据来源支持通过飞书 OAuth 授权后自动读取，或直接粘贴飞书文档链接。"
    )
    return False, message


async def run_agent_safe(
    agent_id: str,
    task_description: str,
    data_summary: Optional[DataSummary],
    upstream_results: Optional[list[AgentResult]],
    feishu_context: Optional[dict],
    user_instructions: Optional[str],
    emitter: EventEmitter,
) -> AgentResult | None:
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
                user_instructions=user_instructions,
            )
            summary = (result.sections[0].content or "")[:100] if result.sections else "完成"
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
    fallback = AgentResult(
        agent_id=agent_id,
        agent_name=agent.agent_name,
        sections=[ResultSection(
            title="执行状态",
            content=f"[{agent.agent_name}] 模块执行失败，已跳过。错误信息：{last_err}"
        )],
        action_items=[],
        raw_output=f"FAILED: {last_err}",
    )
    return fallback


async def orchestrate(
    task_description: str,
    selected_modules: list[str],
    data_summary: Optional[DataSummary],
    feishu_context: Optional[dict],
    emitter: EventEmitter,
    user_instructions: Optional[str] = None,
) -> list[AgentResult]:
    """
    Dependency-aware execution:
    1. Build a dependency graph from selected modules only
    2. Execute in waves: each wave = agents whose dependencies are already done
    3. Within a wave, run agents in parallel
    4. ceo_assistant always in the final wave (SEQUENTIAL_LAST)
    """
    if not selected_modules:
        raise ValueError("未选择任何 Agent 模块，请至少选择一个模块后再执行。")

    can_proceed, no_data_message = _assess_data_availability(data_summary, feishu_context)
    if not can_proceed:
        # Return a single informational result instead of running agents
        no_data_result = AgentResult(
            agent_id="system",
            agent_name="系统提示",
            sections=[ResultSection(title="需要数据", content=no_data_message)],
            action_items=[
                "上传数据文件（.csv / .txt / .md）",
                "选择飞书云文档或电子表格",
                "关联飞书任务或日历事项",
            ],
            raw_output=no_data_message,
        )
        await emitter.emit("task.no_data", payload={"message": no_data_message})
        return [no_data_result]

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
                user_instructions=user_instructions,
                emitter=emitter,
            )
            for aid in ready
        ]
        wave_raw = await asyncio.gather(*wave_tasks, return_exceptions=True)
        wave_results = []
        for aid, res in zip(ready, wave_raw):
            if isinstance(res, AgentResult):
                wave_results.append(res)
                continue
            if isinstance(res, Exception):
                agent = AGENT_REGISTRY.get(aid)
                agent_name = agent.agent_name if agent else aid
                logger.error(f"Agent task failed unexpectedly: {res}")
                try:
                    await emitter.emit_module_failed(aid, agent_name, str(res))
                except Exception as emit_err:
                    logger.error(f"Failed to emit module failure event for {aid}: {emit_err}")
                wave_results.append(AgentResult(
                    agent_id=aid,
                    agent_name=agent_name,
                    sections=[ResultSection(
                        title="执行状态",
                        content=f"[{agent_name}] 模块执行失败，已跳过。错误信息：{res}"
                    )],
                    action_items=[],
                    raw_output=f"FAILED: {res}",
                ))
                continue
            if res is None:
                agent = AGENT_REGISTRY.get(aid)
                agent_name = agent.agent_name if agent else aid
                logger.warning(f"Agent {aid} returned None (not found in registry), skipping")
                wave_results.append(AgentResult(
                    agent_id=aid,
                    agent_name=aid,
                    sections=[ResultSection(
                        title="执行状态",
                        content=f"[{aid}] 模块未注册，已跳过。"
                    )],
                    action_items=[],
                    raw_output="SKIPPED: agent not found in registry",
                ))
        all_results.extend(wave_results)
        completed.update(ready)
        remaining = [aid for aid in remaining if aid not in completed]

    if not all_results:
        raise RuntimeError("所有 Agent 模块均执行失败，任务无结果")

    return all_results
