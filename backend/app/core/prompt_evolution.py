"""Prompt 自演化 — 把高质量反思 promote 为 SYSTEM_PROMPT 持久化注入项。

流程：
  1. _write_reflection 落库后调 maybe_promote(agent_id, reflection_text)
  2. FAST 档 LLM 给反思打分（0-10）+ 提炼成 1-2 句祈使句
  3. 分数 ≥ PROMOTE_THRESHOLD → 写入 AgentPromptHint 表
  4. 每个 (tenant, agent) 软删除最旧的，保留最新 _MAX_HINTS 条
  5. base_agent._call_llm 启动时调 fetch_active_hints(agent_id) 注入

"祈使句"原则：
  - "下次遇到 LTV/CAC 时优先调用 python_calc 而非估算"  ✓
  - "我上次没用工具"  ✗（描述性，不是规则）
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy import select, update

from app.core.observability import get_tenant_id
from app.models.database import AgentPromptHint, AsyncSessionLocal

logger = logging.getLogger(__name__)


PROMOTE_THRESHOLD = 8  # 0-10 量表，>=8 才 promote
MAX_HINTS_PER_AGENT = 5  # 每个 (tenant, agent) 最多激活的 hint 条数


_JUDGE_PROMPT = (
    "你是一位严格的 prompt-engineering 评审。下面是某 AI agent 自评的反思日志。\n\n"
    "请按以下 4 个维度判断这条反思是否值得 promote 成 agent 的 SYSTEM_PROMPT 注入项：\n"
    "  1. 普适性（不是这次任务的孤例，而是同岗位多次会遇到的模式）\n"
    "  2. 可执行（包含具体的工具/方法/动作，而不是『要更好』）\n"
    "  3. 简洁性（能压成 1-2 句祈使句）\n"
    "  4. 不重复（与常识 prompt 不冗余）\n\n"
    "<reflection>\n{reflection}\n</reflection>\n\n"
    "请严格按下列两行格式回复：\n"
    "SCORE=<0-10 整数>\n"
    "RULE=<提炼成 1-2 句祈使句；如分数 < 8 则填 SKIP>"
)


async def maybe_promote(*, agent_id: str, reflection_text: str) -> Optional[int]:
    """对一条反思打分，达标则 promote 入库。返回新 hint 的 id 或 None。"""
    if not agent_id or not reflection_text:
        return None
    try:
        from app.core.llm_client import call_llm

        verdict = await call_llm(
            system_prompt="你是 prompt-engineering 评审，只按指定格式回复，不写多余内容。",
            user_prompt=_JUDGE_PROMPT.format(reflection=reflection_text[:1500]),
            temperature=0,
            max_tokens=200,
            tier="fast",
        )
    except Exception as exc:
        logger.debug("prompt promote judge failed: %s", exc)
        return None

    score_match = re.search(r"SCORE\s*=\s*(\d+)", verdict)
    rule_match = re.search(r"RULE\s*=\s*(.+?)(?:\n|$)", verdict, re.DOTALL)
    if not score_match or not rule_match:
        logger.debug("prompt promote unparseable: %r", verdict[:200])
        return None

    try:
        score = int(score_match.group(1))
    except ValueError:
        return None
    rule_text = rule_match.group(1).strip()
    if score < PROMOTE_THRESHOLD or rule_text.upper().startswith("SKIP") or len(rule_text) < 6:
        logger.info(
            "reflection.not_promoted agent=%s score=%s rule=%r",
            agent_id, score, rule_text[:80],
        )
        return None

    rule_text = rule_text[:300]
    tenant = get_tenant_id() or "default"

    try:
        async with AsyncSessionLocal() as db:
            # 防重复：同 agent + 相同 rule_text 已存在时直接复用
            existing = (
                await db.execute(
                    select(AgentPromptHint).where(
                        AgentPromptHint.tenant_id == tenant,
                        AgentPromptHint.agent_id == agent_id,
                        AgentPromptHint.rule_text == rule_text,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if not existing.active:
                    existing.active = 1
                    await db.commit()
                logger.info("prompt promote dedup-hit agent=%s id=%s", agent_id, existing.id)
                return int(existing.id)

            entry = AgentPromptHint(
                tenant_id=tenant,
                agent_id=agent_id,
                rule_text=rule_text,
                source_summary=reflection_text[:1500],
                score=score,
                active=1,
            )
            db.add(entry)
            await db.flush()
            new_id = int(entry.id)

            # FIFO cap：超出 MAX_HINTS_PER_AGENT 时，把最旧的 active 软删除
            actives = (
                await db.execute(
                    select(AgentPromptHint)
                    .where(
                        AgentPromptHint.tenant_id == tenant,
                        AgentPromptHint.agent_id == agent_id,
                        AgentPromptHint.active == 1,
                    )
                    .order_by(AgentPromptHint.created_at.asc())
                )
            ).scalars().all()
            excess = len(actives) - MAX_HINTS_PER_AGENT
            if excess > 0:
                to_evict = [h.id for h in actives[:excess]]
                await db.execute(
                    update(AgentPromptHint)
                    .where(AgentPromptHint.id.in_(to_evict))
                    .values(active=0)
                )
            await db.commit()
            logger.info(
                "prompt.promoted agent=%s id=%s score=%s rule=%r",
                agent_id, new_id, score, rule_text[:120],
            )
            return new_id
    except Exception as exc:
        logger.warning("prompt promote DB write failed: %s", exc)
        return None


async def fetch_active_hints(agent_id: str) -> list[str]:
    """供 base_agent 启动时拉取。失败返回空列表，永不阻塞主流程。"""
    if not agent_id:
        return []
    tenant = get_tenant_id() or "default"
    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(AgentPromptHint.rule_text)
                .where(
                    AgentPromptHint.tenant_id == tenant,
                    AgentPromptHint.agent_id == agent_id,
                    AgentPromptHint.active == 1,
                )
                .order_by(AgentPromptHint.score.desc(), AgentPromptHint.created_at.desc())
                .limit(MAX_HINTS_PER_AGENT)
            )
            return list((await db.execute(stmt)).scalars().all())
    except Exception as exc:
        logger.debug("fetch_active_hints failed: %s", exc)
        return []


def format_hints_block(hints: list[str]) -> str:
    if not hints:
        return ""
    lines = ["\n=== 经验内化（来自过往反思的高分 promote 规则）===\n"]
    for i, h in enumerate(hints, 1):
        lines.append(f"  {i}. {h}")
    lines.append("")
    return "\n".join(lines)
