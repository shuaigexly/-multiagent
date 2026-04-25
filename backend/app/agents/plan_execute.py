"""Plan-and-Execute 高级模式 — 把单次大 prompt 拆成 plan→execute→synthesize 三阶段。

为什么：
  - 一次性 prompt 让 LLM 同时承担"列结构 + 找数据 + 写结论"三件事，质量参差
  - Plan-Execute 让 LLM 分层思考：先列要回答的子问题，再针对每个子问题独立分析（可调工具），
    最后把子答案综合 — 跟人类做复杂分析的步骤一致

启用：BaseAgent 子类设 plan_execute_enabled = True；当前默认仅 ceo_assistant 启用。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)


_PLAN_PROMPT = (
    "请为以下任务列出 3-5 个具体的子问题（sub-questions），每个子问题：\n"
    "  - 必须是独立可回答的（不依赖其他子问题）\n"
    "  - 必须聚焦数据 / 决策 / 行动其中之一\n"
    "  - 不要太宏观（不要『分析整体』），不要太琐碎\n\n"
    "<task>\n{task}\n</task>\n\n"
    "{upstream_block}\n\n"
    "只输出严格 JSON 数组，不要其他文字：\n"
    '[{"step": "用一句话描述子问题", "why": "回答它能解决什么", "category": "data|decision|action"}]\n'
)


_EXECUTE_PROMPT = (
    "现在你正在执行子问题 #{idx}/{total}：\n"
    "<sub_question>\n{step}\n</sub_question>\n"
    "回答此子问题的目的：{why}\n\n"
    "请基于以下整体上下文 + 上游分析，针对**仅这一个子问题**给出聚焦答案（200-400 字），"
    "包含至少 1 个量化数据/具体动作。如果有可用工具（fetch_url/python_calc 等）应主动调用。\n\n"
    "<task>\n{task}\n</task>\n\n"
    "{upstream_block}"
)


_SYNTHESIZE_PROMPT = (
    "你已分别回答了下列子问题，现在请把它们整合成一份完整分析。\n\n"
    "<task>\n{task}\n</task>\n\n"
    "<sub_answers>\n{sub_answers}\n</sub_answers>\n\n"
    "整合要求：\n"
    "  - 用 ## 二级标题划分清晰章节\n"
    "  - 行动项放在最后用 ## 行动建议 列出\n"
    "  - 末尾仍需附 ```metadata``` JSON 块（health/confidence/actions），按之前的硬要求执行\n"
)


async def run_plan_execute(
    *,
    agent,
    task_description: str,
    upstream_block: str = "",
    max_steps: int = 5,
) -> str:
    """执行 plan→execute→synthesize 三阶段，返回最终 raw 文本。

    任一阶段失败抛异常，由调用方走 fallback 路径。
    """
    from app.core.llm_client import call_llm

    # ------ Phase 1: Plan ------
    plan_prompt = _PLAN_PROMPT.format(
        task=task_description[:1500],
        upstream_block=upstream_block[:3000] if upstream_block else "<no_upstream/>",
    )
    plan_raw = await call_llm(
        system_prompt="你是一位严格的任务分解师。只输出合法 JSON 数组。",
        user_prompt=plan_prompt,
        temperature=0.3,
        max_tokens=600,
        tier="standard",
    )
    plan_raw = plan_raw.strip()
    # 容错：去 ```json 包裹
    if plan_raw.startswith("```"):
        plan_raw = plan_raw.split("```", 2)[1]
        if plan_raw.lstrip().startswith("json"):
            plan_raw = plan_raw.split("\n", 1)[1] if "\n" in plan_raw else plan_raw[4:]
    try:
        plan = json.loads(plan_raw)
        if not isinstance(plan, list):
            raise ValueError("plan is not a list")
    except Exception as exc:
        raise RuntimeError(f"plan parse failed: {exc}; raw={plan_raw[:300]}")

    plan = [p for p in plan if isinstance(p, dict) and p.get("step")][:max_steps]
    if len(plan) < 2:
        raise RuntimeError(f"plan too short: only {len(plan)} valid steps")
    logger.info("plan_execute.plan agent=%s steps=%s", agent.agent_id, len(plan))

    # ------ Phase 2: Execute (each sub-question) ------
    sub_answers: list[str] = []
    for idx, step in enumerate(plan, 1):
        exec_prompt = _EXECUTE_PROMPT.format(
            idx=idx,
            total=len(plan),
            step=step.get("step", "")[:300],
            why=step.get("why", "")[:200],
            task=task_description[:1000],
            upstream_block=upstream_block[:2000] if upstream_block else "<no_upstream/>",
        )
        try:
            ans = await agent._call_llm(exec_prompt)
        except Exception as exc:
            logger.warning("plan_execute step %s failed: %s", idx, exc)
            ans = f"（子问题 {idx} 执行失败：{exc}）"
        sub_answers.append(f"### [{idx}] {step.get('step', '')}\n{truncate_with_marker(ans, 1500)}")

    # ------ Phase 3: Synthesize ------
    synth_prompt = _SYNTHESIZE_PROMPT.format(
        task=task_description[:1000],
        sub_answers=truncate_with_marker("\n\n".join(sub_answers), 8000),
    )
    final_raw = await agent._call_llm(synth_prompt, force_tier="deep")
    return final_raw
