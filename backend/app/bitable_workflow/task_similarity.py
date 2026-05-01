"""跨任务相似度检索 — 七岗多智能体的长期记忆（v8.6.20-r40）。

设计动机
========
七岗 DAG 跑过的每条任务都会沉淀完整的 CEO 综合报告 + 决策摘要 + 行动项。但
这些过往输出只能靠用户在飞书 Bitable 里翻历史看 — AI 自己没有"我以前分析过
类似问题"的记忆。

本模块基于 Jaccard 相似度做一层零依赖的跨任务召回：用户提一条新任务，系统
扫最近 200 条「已完成」记录，按 (title × 2 + dimension × 0.5 + background × 0.3)
加权打分，返回 top_k 最相似的过往任务。下游可：
- 在 CEO prompt 里注入 `<similar_past_analyses>` 段（让 LLM 借鉴）
- 前端"创建任务"页面提示用户"6 个月前你分析过类似的：[xxx]"
- 评审场景演示 AI 系统的连续学习能力

为什么不上 embedding？
========================
1. 嵌入模型依赖 sentence-transformers 或外部 API → 部署复杂度↑↑、推理 latency↑
2. 中文短文本 + 业务领域词（增长 / 留存 / GMV）的字符重叠已经足够区分相似度
3. Jaccard 实现 < 100 行、无外部依赖、可解释、单测好覆盖
4. 后续若需要 embedding 升级，本模块的 score_similarity 接口稳定，可平滑切

后续可扩展点
=============
- TF-IDF 加权（停用词过滤 + 低频词加权）
- 嵌入向量缓存（任务完成时算一次存 Redis，召回时 cosine）
- 时间衰减（半年前的相似度打 0.7 折）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.scheduler import _flatten_text_value
from app.bitable_workflow.schema import Status

logger = logging.getLogger(__name__)


# 中文常见连接词 / 助词 / 量词，过滤掉避免拉高所有任务的相似度
_STOP_TOKENS = frozenset(
    "的 了 在 是 我 有 和 就 不 人 都 一 个 上 也 很 到 说 要 去 你 会 着 没 看 好 自 这 然".split()
    + ["a", "an", "the", "of", "in", "on", "at", "to", "for", "by", "and", "or"]
)


def _tokenize(text: str) -> set[str]:
    """简单跨语言分词：
    - 连续 ASCII 字母数字 → 整体作为一个 token（小写）
    - 单个 CJK 字符 → 每字一个 token
    - 标点 / 空白 → 分隔符
    - 停用词过滤
    """
    if not text:
        return set()
    text = text.strip().lower()
    tokens: list[str] = []
    # 一次扫描：抓 [a-z0-9]+ 作为英文 token；其他 CJK 字符逐字
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isascii() and (ch.isalnum()):
            # 英文 / 数字 token
            j = i
            while j < len(text) and text[j].isascii() and text[j].isalnum():
                j += 1
            tokens.append(text[i:j])
            i = j
        elif "一" <= ch <= "鿿":
            tokens.append(ch)
            i += 1
        else:
            i += 1  # 跳过空白 / 标点
    return {t for t in tokens if t not in _STOP_TOKENS and len(t) >= 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


@dataclass(frozen=True)
class SimilarTask:
    record_id: str
    title: str
    dimension: str
    score: float
    health: str = ""           # 综合健康度 emoji
    completed_at: str = ""     # 完成时间字符串（可空）
    summary: str = ""          # CEO 决策摘要前 200 字（如能拿到）

    def render_brief(self) -> str:
        bits = [self.title]
        if self.dimension:
            bits.append(f"({self.dimension})")
        if self.health:
            bits.append(self.health)
        return " ".join(bits) + f"  · 相似度 {self.score:.2f}"


def score_similarity(
    *,
    query_title: str,
    query_dimension: str,
    query_background: str,
    candidate_title: str,
    candidate_dimension: str,
    candidate_background: str,
) -> float:
    """加权 Jaccard 综合分。

    权重设计：
    - title: × 2.0（最强信号）
    - dimension: × 0.5（同维度说明分析角度可借鉴）
    - background: × 0.3（语境辅助，但短文本噪声大）

    返回 0.0-1.0 区间（理论上限 = 1+0.5+0.3 但极少满分）。
    """
    title_score = _jaccard(_tokenize(query_title), _tokenize(candidate_title)) * 2.0
    if query_dimension and candidate_dimension and query_dimension == candidate_dimension:
        dimension_score = 0.5
    else:
        dimension_score = _jaccard(_tokenize(query_dimension), _tokenize(candidate_dimension)) * 0.5
    bg_score = _jaccard(_tokenize(query_background), _tokenize(candidate_background)) * 0.3
    return title_score + dimension_score + bg_score


async def find_similar_completed_tasks(
    *,
    app_token: str,
    table_id: str,
    query_title: str,
    query_dimension: str = "",
    query_background: str = "",
    top_k: int = 3,
    min_score: float = 0.1,
    max_scan: int = 200,
) -> list[SimilarTask]:
    """从分析任务表里扫最近 max_scan 条已完成记录，返回打分 ≥ min_score 的 top_k。

    Args:
        app_token / table_id: 主任务表
        query_title / query_dimension / query_background: 新任务的内容
        top_k: 最多返回多少条相似任务
        min_score: 低于此分忽略（避免返回明显不相关的）
        max_scan: 最多扫多少条历史记录（防 base 数据量上去后扫描爆炸）

    Returns:
        list[SimilarTask] 按 score 倒序，长度 ≤ top_k。
    """
    if not query_title or not query_title.strip():
        return []

    # 已完成 + 已归档 都算可借鉴的历史记忆
    filter_expr = (
        f'OR(CurrentValue.[状态]="{Status.COMPLETED}",CurrentValue.[状态]="{Status.ARCHIVED}")'
    )
    try:
        records = await bitable_ops.list_records(
            app_token, table_id, filter_expr=filter_expr, max_records=max_scan
        )
    except Exception as exc:
        logger.warning("similar tasks scan failed: %s", exc)
        return []

    scored: list[SimilarTask] = []
    for row in records:
        rid = str(row.get("record_id") or "").strip()
        if not rid:
            continue
        fields = row.get("fields") or {}
        c_title = str(_flatten_text_value(fields.get("任务标题")) or "").strip()
        if not c_title:
            continue
        c_dim = str(_flatten_text_value(fields.get("分析维度")) or "").strip()
        c_bg = str(_flatten_text_value(fields.get("背景说明")) or "").strip()
        c_health = str(_flatten_text_value(fields.get("综合健康度")) or "").strip()
        c_completed = str(_flatten_text_value(fields.get("完成时间")) or "").strip()
        c_summary = str(_flatten_text_value(fields.get("决策摘要")) or "").strip()

        score = score_similarity(
            query_title=query_title,
            query_dimension=query_dimension,
            query_background=query_background,
            candidate_title=c_title,
            candidate_dimension=c_dim,
            candidate_background=c_bg,
        )
        if score < min_score:
            continue
        scored.append(SimilarTask(
            record_id=rid,
            title=c_title,
            dimension=c_dim,
            score=round(score, 3),
            health=c_health,
            completed_at=c_completed,
            summary=c_summary[:200],
        ))

    scored.sort(key=lambda x: (-x.score, x.title))
    return scored[:top_k]
