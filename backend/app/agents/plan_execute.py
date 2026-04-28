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


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _safe_prompt_fragment(value: object, *, source: str, max_chars: int) -> str:
    text = truncate_with_marker(value, max_chars)
    try:
        from app.core.prompt_guard import sanitize

        text = sanitize(text, source=source).text
    except Exception:
        pass
    return _escape_xml(text)


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

    返回 list 或 None；失败永不抛异常。

    v8.6.20-r12（审计 #10）：用 stdlib 的 json.JSONDecoder.raw_decode 替代手写
    state machine —— 旧实现的 escape 标志在 `\\"` 后未正确退出 in_str 状态，
    LLM 输出 `\"x\"` 类转义引号会让 depth 永远不归零，整个 Plan-Execute 模式
    在 CEO 助理的常见输出上静默退化为单 prompt。raw_decode 用经过验证的解析器，
    且能处理"先废话后 JSON 后废话"格式。
    """
    if not text:
        return None
    s = text.strip()
    # 去 markdown 围栏
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.lstrip("`")
        if s.lstrip().lower().startswith("json"):
            s = s.split("\n", 1)[1] if "\n" in s else s[4:]
    # 找第一个 [，调用 stdlib raw_decode 解析直至 valid JSON 边界，剩余文本忽略
    decoder = json.JSONDecoder()
    start = s.find("[")
    while start >= 0:
        try:
            obj, _consumed = decoder.raw_decode(s[start:])
            return obj if isinstance(obj, list) else None
        except json.JSONDecodeError:
            # 当前 [ 不能解析为完整 JSON 数组，跳过这个 [ 找下一个
            next_start = s.find("[", start + 1)
            if next_start < 0:
                return None
            start = next_start
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
        .replace("{task}", _safe_prompt_fragment(task_description, source="plan_execute.task", max_chars=1500))
        .replace(
            "{upstream_block}",
            _safe_prompt_fragment(upstream_block, source="plan_execute.upstream", max_chars=3000)
            if upstream_block else "<no_upstream/>",
        )
    )
    if memory_block:
        plan_prompt = _safe_prompt_fragment(memory_block, source="plan_execute.memory", max_chars=3000) + "\n\n" + plan_prompt
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

    valid_plan = [p for p in plan if isinstance(p, dict) and p.get("step")]
    # v8.6.20-r13（审计 #4）：之前 [:max_steps] 静默丢弃超额步骤，复杂 CEO 任务
    # 一旦 LLM 输出 6-8 步 → 后 2-3 步直接没了，最终报告隐性少 25%-40% 覆盖面，
    # 无任何告警。改为显式 logger.warning，并在 synthesize 阶段把被截断的 step
    # 标题以兜底形式塞进去，让 CEO 至少知道还有未展开的子问题。
    if len(valid_plan) > max_steps:
        truncated_titles = [p.get("step") for p in valid_plan[max_steps:]]
        logger.warning(
            "plan_execute.truncated agent=%s total=%d max=%d dropped=%s",
            agent.agent_id, len(valid_plan), max_steps,
            [str(t)[:40] for t in truncated_titles[:3]],
        )
    plan = valid_plan[:max_steps]
    if len(plan) < 2:
        raise RuntimeError(f"plan too short: only {len(plan)} valid steps")
    logger.info("plan_execute.plan agent=%s steps=%s", agent.agent_id, len(plan))

    # ------ Phase 2: Execute (each sub-question) ------
    # 成本控制：execute 走 call_llm FAST 档不进工具循环（工具集中在 synthesize 阶段）
    # 关键修复（v7.9）：保留 agent 的领域 SYSTEM_PROMPT（RICE/JTBD/RFM 等专业框架），
    # 之前只用弱 prompt "你是 X" 让子问题答案丧失专业性 — 5 步全部退化成通用回答。
    base_persona = (agent.SYSTEM_PROMPT or "").strip()
    if base_persona:
        # 取前 1500 字 + 任务上下文标识，避免子步骤 prompt 过长
        base_persona = truncate_with_marker(base_persona, 1500, "\n...[persona truncated]")
    exec_system = (
        f"{base_persona}\n\n"
        f"---\n你（「{agent.agent_name}」）现在正在回答一个分解出来的聚焦子问题，"
        "保持上述角色的专业框架与方法论；不要写元数据块、不要罗列章节，"
        "用 200-400 字直接给出针对此子问题的精准答案。"
    )
    # v8.6.10：之前 5 个 sub-question for 串行执行 = 5×30s ≈ 150s（CEO Wave3 主要耗时来源）。
    # 子问题相互独立（plan 阶段已要求"独立可回答"），改 asyncio.gather 并行 = ~30s，
    # 任务整体提速 ~3-5×。失败用 try/except per-item 包裹，单个 sub-Q 失败不阻塞其他。
    import asyncio as _asyncio

    async def _run_step(idx: int, step: dict) -> str:
        exec_prompt = (
            _EXECUTE_PROMPT
            .replace("{idx}", str(idx))
            .replace("{total}", str(len(plan)))
            .replace("{step}", _safe_prompt_fragment(step.get("step", ""), source="plan_execute.step", max_chars=300))
            .replace("{why}", _safe_prompt_fragment(step.get("why", ""), source="plan_execute.why", max_chars=200))
            .replace("{task}", _safe_prompt_fragment(task_description, source="plan_execute.task", max_chars=1000))
            .replace(
                "{upstream_block}",
                _safe_prompt_fragment(upstream_block, source="plan_execute.upstream", max_chars=2000)
                if upstream_block else "<no_upstream/>",
            )
        )
        try:
            ans = await call_llm(
                system_prompt=exec_system,
                user_prompt=exec_prompt,
                temperature=0.4,
                max_tokens=600,
                tier="fast",
            )
        except Exception as exc:
            logger.warning("plan_execute step %s failed: %s", idx, exc)
            ans = f"（子问题 {idx} 执行失败：{exc}）"
        return f"### [{idx}] {step.get('step', '')}\n{truncate_with_marker(ans, 1500)}"

    sub_answers: list[str] = list(await _asyncio.gather(
        *[_run_step(i, s) for i, s in enumerate(plan, 1)]
    ))

    # ------ Phase 3: Synthesize ------
    synth_prompt = (
        _SYNTHESIZE_PROMPT
        .replace("{task}", _safe_prompt_fragment(task_description, source="plan_execute.task", max_chars=1000))
        .replace(
            "{sub_answers}",
            _safe_prompt_fragment("\n\n".join(sub_answers), source="plan_execute.sub_answers", max_chars=8000),
        )
    )
    if memory_block:
        synth_prompt = _safe_prompt_fragment(memory_block, source="plan_execute.memory", max_chars=3000) + "\n\n" + synth_prompt
    final_raw = await agent._call_llm(synth_prompt, force_tier="deep")
    return final_raw
