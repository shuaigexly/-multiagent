"""Agent 长期记忆 — 跨任务召回过往相似案例。

存储：
  - SQLAlchemy 表 AgentMemory：(tenant_id, agent_id, task_hash, task_text, summary, embedding_json)
  - 每个 agent 在 analyze 完成后存一条；store_memory 自动提取 summary 前 800 字
  - 检索：query_memories(agent_id, task_text, k=3) 返回 top-k 相似案例

Embedding 方案（自动选最佳）：
  1. 优先：调 OpenAI 兼容 embeddings 接口（设 LLM_EMBEDDING_MODEL 启用，如 text-embedding-3-small / embedding-2）
  2. 回退：hash-based BoW（中文 char 2-gram + 英文 token 哈希），128 维
     —— 不依赖外部服务，离线可用；语义弱但比关键词匹配强

相似度：纯 Python cosine similarity（不依赖 numpy）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select

from app.core.observability import get_tenant_id
from app.models.database import AgentMemory, AsyncSessionLocal

logger = logging.getLogger(__name__)


_DIM_FALLBACK = 128


@dataclass
class MemoryHit:
    task_text: str
    summary: str
    similarity: float
    created_at: str


def _hash_embedding(text: str, dim: int = _DIM_FALLBACK) -> list[float]:
    """无外部依赖的 BoW 嵌入。中文 char-2gram + 英文 word，hash 到固定维度。"""
    text = (text or "").lower().strip()
    if not text:
        return [0.0] * dim
    vec = [0.0] * dim
    # 英文/数字 token
    for token in re.findall(r"[a-z0-9]+", text):
        idx = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0
    # 中文 char-2gram
    cleaned = re.sub(r"[a-z0-9\s]+", "", text)
    for i in range(len(cleaned) - 1):
        bigram = cleaned[i:i + 2]
        idx = int(hashlib.md5(bigram.encode("utf-8")).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


async def _openai_embedding(text: str) -> Optional[list[float]]:
    model = os.getenv("LLM_EMBEDDING_MODEL", "").strip()
    if not model:
        return None
    try:
        from openai import AsyncOpenAI

        from app.core.settings import get_llm_api_key, get_llm_base_url

        client = AsyncOpenAI(api_key=get_llm_api_key(), base_url=get_llm_base_url())
        resp = await asyncio.wait_for(
            client.embeddings.create(model=model, input=[text[:4000]]),
            timeout=10.0,
        )
        return list(resp.data[0].embedding)
    except Exception as exc:
        logger.debug("embedding API failed (fallback to hash): %s", exc)
        return None


async def _embed(text: str) -> list[float]:
    vec = await _openai_embedding(text)
    if vec:
        return vec
    return _hash_embedding(text)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _task_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


async def store_memory(
    *,
    agent_id: str,
    task_text: str,
    summary: str,
) -> None:
    """落库一条 agent 记忆。失败仅 warning，不阻塞主流程。"""
    if not agent_id or not task_text or not summary:
        return
    tenant = get_tenant_id() or "default"
    try:
        embedding = await _embed(task_text)
        async with AsyncSessionLocal() as db:
            entry = AgentMemory(
                tenant_id=tenant,
                agent_id=agent_id,
                task_hash=_task_hash(task_text),
                task_text=task_text[:2000],
                summary=summary[:2000],
                embedding_json=json.dumps(embedding, ensure_ascii=False),
            )
            db.add(entry)
            await db.commit()
    except Exception as exc:
        logger.warning("store_memory failed agent=%s err=%s", agent_id, exc)


async def query_memories(
    *,
    agent_id: str,
    task_text: str,
    k: int = 3,
    min_similarity: float = 0.25,
) -> list[MemoryHit]:
    """检索过往最相似的 k 条 agent 记忆。"""
    if not agent_id or not task_text:
        return []
    tenant = get_tenant_id() or "default"
    try:
        query_vec = await _embed(task_text)
        async with AsyncSessionLocal() as db:
            stmt = (
                select(AgentMemory)
                .where(AgentMemory.tenant_id == tenant, AgentMemory.agent_id == agent_id)
                .order_by(AgentMemory.created_at.desc())
                .limit(200)
            )
            rows = (await db.execute(stmt)).scalars().all()
    except Exception as exc:
        logger.debug("query_memories DB failed: %s", exc)
        return []

    scored: list[tuple[float, AgentMemory]] = []
    for r in rows:
        try:
            stored = json.loads(r.embedding_json or "[]")
        except Exception:
            continue
        if not stored or len(stored) != len(query_vec):
            continue
        sim = _cosine(query_vec, stored)
        if sim >= min_similarity:
            scored.append((sim, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        MemoryHit(
            task_text=r.task_text,
            summary=r.summary,
            similarity=round(sim, 3),
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for sim, r in scored[:k]
    ]


def format_memory_hits(hits: list[MemoryHit]) -> str:
    """把检索结果格式化为 prompt 可注入的文本块。"""
    if not hits:
        return ""
    lines = ["<long_term_memory>", "（基于过往相似任务的同岗位历史结论，仅供参考，不要复制粘贴）"]
    for i, h in enumerate(hits, 1):
        lines.append(
            f"  [案例{i}] 相似度={h.similarity:.2f} 时间={h.created_at[:10]}\n"
            f"    任务：{h.task_text[:200]}\n"
            f"    结论摘要：{h.summary[:400]}"
        )
    lines.append("</long_term_memory>")
    return "\n".join(lines)
