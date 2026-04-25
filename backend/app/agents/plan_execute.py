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


def _extract_first_json_array(text: str):
    """从 LLM 输出中提取第一个完整 JSON 数组（容错 markdown 围栏 / 前置废话 / 尾部废话）。

    返回 list[dict] 或 None；失败永不抛异常。
    """
    if not text:
        return None
    # 第一步：去 markdown 围栏
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.lstrip("`")
        if s.lstrip().startswith("json"):
            s = s.split("\n", 1)[1] if "\n" in s else s[4:]
    # 第二步：扫描第一个 [ 与匹配的 ]，跟踪转义和字符串内的方括号
    start = s.find("[")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        ch = s[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                candidate = s[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None
    return None


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
    memory_block: str = "",
) -> str:
    """执行 plan→execute→synthesize 三阶段，返回最终 raw 文本。

    任一阶段失败抛异常，由调用方走 fallback 路径。
    memory_block 由调用方传入（包含长期记忆 + 反思 hints），统一注入到 plan/synthesize 阶段。
    """
    from app.core.llm_client import call_llm

    # ------ Phase 1: Plan ------
    # 关键修复（v7.8）：用 replace 而不是 format —— task_description 含 {var} / JSON 花括号
    # 会让 .format() 抛 KeyError。这与 base_agent.USER_PROMPT_TEMPLATE 已采用的同一防护。
    plan_prompt = (
        _PLAN_PROMPT
        .replace("{task}", task_description[:1500])
        .replace("{upstream_block}", upstream_block[:3000] if upstream_block else "<no_upstream/>")
    )
    if memory_block:
        plan_prompt = memory_block + "\n\n" + plan_prompt
    plan_raw = await call_llm(
        system_prompt="你是一位严格的任务分解师。只输出合法 JSON 数组。",
        user_prompt=plan_prompt,
        temperature=0.3,
        max_tokens=600,
        tier="standard",
    )
    plan_raw = plan_raw.strip()
    plan = _extract_first_json_array(plan_raw)
    if plan is None:
        raise RuntimeError(f"plan parse failed: no JSON array; raw={plan_raw[:300]}")
    if not isinstance(plan, list):
        raise RuntimeError(f"plan parse: not a list; raw={plan_raw[:300]}")

    plan = [p for p in plan if isinstance(p, dict) and p.get("step")][:max_steps]
    if len(plan) < 2:
        raise RuntimeError(f"plan too short: only {len(plan)} valid steps")
    logger.info("plan_execute.plan agent=%s steps=%s", agent.agent_id, len(plan))

    # ------ Phase 2: Execute (each sub-question) ------
    # 成本控制：execute 阶段直接走 call_llm（FAST 档）+ 不进工具循环，否则
    # 5 步 × 4 工具迭代 = 20 次 LLM 调用，单任务成本失控。工具调用集中在 synthesize 阶段。
    sub_answers: list[str] = []
    for idx, step in enumerate(plan, 1):
        exec_prompt = (
            _EXECUTE_PROMPT
            .replace("{idx}", str(idx))
            .replace("{total}", str(len(plan)))
            .replace("{step}", str(step.get("step", ""))[:300])
            .replace("{why}", str(step.get("why", ""))[:200])
            .replace("{task}", task_description[:1000])
            .replace("{upstream_block}", upstream_block[:2000] if upstream_block else "<no_upstream/>")
        )
        try:
            ans = await call_llm(
                system_prompt=f"你是「{agent.agent_name}」，正在回答任务的一个聚焦子问题。",
                user_prompt=exec_prompt,
                temperature=0.4,
                max_tokens=600,
                tier="fast",
            )
        except Exception as exc:
            logger.warning("plan_execute step %s failed: %s", idx, exc)
            ans = f"（子问题 {idx} 执行失败：{exc}）"
        sub_answers.append(f"### [{idx}] {step.get('step', '')}\n{truncate_with_marker(ans, 1500)}")

    # ------ Phase 3: Synthesize ------
    synth_prompt = (
        _SYNTHESIZE_PROMPT
        .replace("{task}", task_description[:1000])
        .replace("{sub_answers}", truncate_with_marker("\n\n".join(sub_answers), 8000))
    )
    if memory_block:
        synth_prompt = memory_block + "\n\n" + synth_prompt
    final_raw = await agent._call_llm(synth_prompt, force_tier="deep")
    return final_raw
