"""LLM-as-Judge — 让 DEEP 档模型对比多个候选输出，选最佳。

使用场景：
  - CEO 助理同时跑 STANDARD + DEEP 两版，judge 选优
  - 自动质量重试时同时保留新旧版，judge 选优（替代单纯比较 confidence）
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)


_JUDGE_PROMPT = (
    "你是一位严格的输出质量评审。请对比下列候选答案，选出最佳的一个。\n\n"
    "评判标准（按权重）：\n"
    "  1. 量化具体度（含真实数字、具体名词、可执行动作）权重 40%\n"
    "  2. 逻辑严密度（推理链清晰、归因层级深）权重 30%\n"
    "  3. 完整度（覆盖任务的关键维度）权重 20%\n"
    "  4. 行动可执行性（行动项有 owner / due / metric）权重 10%\n\n"
    "<task>\n{task}\n</task>\n\n"
    "{candidates}\n\n"
    "只回复一行：BEST=<候选编号>；REASON=<30 字内简短理由>"
)


async def judge_best(
    *,
    task_description: str,
    candidates: list[str],
) -> int:
    """对比多个候选，返回最佳的索引（0-based）。

    候选 < 2 时直接返回 0；judge LLM 失败时回退到「选最长」启发式。
    """
    if not candidates:
        return -1
    if len(candidates) == 1:
        return 0

    block_lines = []
    for idx, cand in enumerate(candidates):
        block_lines.append(
            f"<candidate_{idx + 1}>\n{truncate_with_marker(cand, 3000)}\n</candidate_{idx + 1}>"
        )
    candidates_block = "\n\n".join(block_lines)

    from app.core.llm_client import call_llm

    try:
        verdict = await call_llm(
            system_prompt="你是 LLM-as-Judge，严格按规则评判输出质量，不写多余话。",
            user_prompt=_JUDGE_PROMPT.format(
                task=truncate_with_marker(task_description, 800),
                candidates=candidates_block,
            ),
            temperature=0,
            max_tokens=120,
            tier="deep",
        )
    except Exception as exc:
        logger.warning("judge LLM failed, falling back to longest: %s", exc)
        return _longest_idx(candidates)

    # 解析 BEST=<idx>
    m = re.search(r"BEST\s*=\s*(\d+)", verdict, re.IGNORECASE)
    if not m:
        logger.debug("judge verdict unparsable, fallback to longest: %r", verdict[:100])
        return _longest_idx(candidates)
    idx_1based = int(m.group(1))
    if 1 <= idx_1based <= len(candidates):
        logger.info("judge picked candidate %s — verdict=%r", idx_1based, verdict[:100])
        return idx_1based - 1
    return _longest_idx(candidates)


def _longest_idx(candidates: list[str]) -> int:
    return max(range(len(candidates)), key=lambda i: len(candidates[i] or ""))
