"""跨 agent Q&A 协议 — Wave3 CEO 助理可对 Wave1/2 同侪提追问。

设计：
  - 通过 ContextVar 把 "当前 agent 的同侪结果集" 传到 ask_peer 工具
  - LLM 决定调用 ask_peer(agent_id, question) 时，工具拿对应同侪的 raw_output
    作为上下文，发起一次定向 LLM 调用并把回答返回给主流程
  - 严格防环：peer 在被 ask 时禁用 ask_peer 工具自身，避免互相递归

注册时机：每条任务进入 Wave3 之前，把 wave1+wave2 结果通过 set_peer_pool 注册。
"""
from __future__ import annotations

import contextvars
import logging
from typing import Optional

from app.agents.base_agent import AgentResult
from app.agents.tools import register_tool
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)

_peer_pool: contextvars.ContextVar[Optional[dict[str, AgentResult]]] = contextvars.ContextVar(
    "peer_pool", default=None
)


def set_peer_pool(results: list[AgentResult] | None) -> contextvars.Token:
    """把同侪结果集注入当前 asyncio context；返回 token，调用方 reset() 清理。"""
    pool = {r.agent_id: r for r in (results or [])}
    return _peer_pool.set(pool)


def clear_peer_pool(token: contextvars.Token) -> None:
    _peer_pool.reset(token)


def get_peer_summary() -> str:
    pool = _peer_pool.get() or {}
    if not pool:
        return "（当前无可追问的同侪）"
    lines = []
    for aid, r in pool.items():
        first_section = r.sections[0].content[:300] if r.sections else ""
        lines.append(f"  - {aid} ({r.agent_name})：{truncate_with_marker(first_section, 200)}")
    return "\n".join(lines)


@register_tool(
    name="ask_peer",
    description=(
        "向同侪 agent 提一个具体追问，获得基于其完整分析上下文的针对性回答。"
        "适合 CEO 助理在汇总时澄清歧义、获取数据细节，避免凭空猜测。"
        "agent_id 必须是已知岗位 ID：data_analyst / content_manager / seo_advisor /"
        " product_manager / operations_manager / finance_advisor"
    ),
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "目标 agent 的 agent_id",
                "enum": [
                    "data_analyst",
                    "content_manager",
                    "seo_advisor",
                    "product_manager",
                    "operations_manager",
                    "finance_advisor",
                ],
            },
            "question": {
                "type": "string",
                "description": "对该 agent 的具体追问，单一、聚焦、不要复合",
            },
        },
        "required": ["agent_id", "question"],
    },
)
async def ask_peer(agent_id: str, question: str) -> str:
    pool = _peer_pool.get() or {}
    peer = pool.get(agent_id)
    if peer is None:
        return f"ERROR: peer '{agent_id}' not in current pool. Available: {', '.join(pool.keys())}"

    from app.core.llm_client import call_llm

    sections_text = "\n".join(
        f"## {s.title}\n{s.content}" for s in peer.sections
    )
    actions_text = "\n".join(f"- {a}" for a in peer.action_items[:10])
    context = (
        f"你之前作为「{peer.agent_name}」对当前任务的完整分析如下：\n"
        f"<previous_analysis>\n"
        f"{truncate_with_marker(sections_text, 4000)}\n"
        f"\n[行动项]\n{truncate_with_marker(actions_text, 1000)}\n"
        f"</previous_analysis>"
    )
    prompt = (
        f"{context}\n\n"
        f"现在 CEO 助理向你提问：\n<question>\n{truncate_with_marker(question, 500)}\n</question>\n\n"
        "请基于你之前的分析数据精准回答；如果你之前没分析过该方面，直接说「数据未覆盖」。"
        "回答控制在 200 字以内，不要重复完整分析。"
    )
    try:
        answer = await call_llm(
            system_prompt=f"你是「{peer.agent_name}」，正在被 CEO 助理追问。基于自己的过往分析直接精准回答。",
            user_prompt=prompt,
            temperature=0.3,
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("ask_peer LLM failed: agent=%s err=%s", agent_id, exc)
        return f"ERROR: peer '{agent_id}' failed to answer: {exc}"
    return truncate_with_marker(answer.strip(), 800)
