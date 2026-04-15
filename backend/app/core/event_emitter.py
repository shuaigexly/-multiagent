"""
EventEmitter: 统一事件落库 + Redis 广播
- 原子分配 sequence（在同一事务内递增 tasks.last_sequence）
- 先落库提交，再 Redis PUBLISH
- 是唯一允许写 task_events 和发 Redis 的入口
"""
import json
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import Task, TaskEvent

logger = logging.getLogger(__name__)


class EventEmitter:
    def __init__(self, task_id: str, db: AsyncSession, redis_client=None):
        self.task_id = task_id
        self.db = db
        self.redis = redis_client

    async def emit(
        self,
        event_type: str,
        agent_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> int:
        """Allocate sequence with CAS retry, persist event, commit, then publish."""
        new_seq = await self._next_sequence()

        event = TaskEvent(
            task_id=self.task_id,
            sequence=new_seq,
            event_type=event_type,
            agent_id=agent_id,
            agent_name=agent_name,
            payload=payload or {},
            created_at=datetime.utcnow(),
        )
        self.db.add(event)
        # Commit before Redis publish so consumers never see uncommitted events
        await self.db.commit()

        if self.redis:
            try:
                message = json.dumps(
                    {
                        "task_id": self.task_id,
                        "sequence": new_seq,
                        "event_type": event_type,
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "payload": payload or {},
                    },
                    ensure_ascii=False,
                )
                await self.redis.publish(f"task:{self.task_id}", message)
            except Exception as e:
                logger.warning(f"Redis publish failed (non-fatal): {e}")

        return new_seq

    async def _next_sequence(self) -> int:
        """Increment last_sequence using optimistic CAS; retry on concurrent modification."""
        for _ in range(5):
            result = await self.db.execute(
                select(Task.last_sequence).where(Task.id == self.task_id)
            )
            current = result.scalar_one_or_none() or 0
            new_seq = current + 1
            update_result = await self.db.execute(
                update(Task)
                .where(Task.id == self.task_id, Task.last_sequence == current)
                .values(last_sequence=new_seq, updated_at=datetime.utcnow())
            )
            if update_result.rowcount == 1:
                return new_seq
            await asyncio.sleep(0.01)
        raise RuntimeError(f"Failed to allocate event sequence for task {self.task_id}")

    async def emit_task_recognized(self, task_type: str, task_type_label: str, modules: list):
        await self.emit(
            "task.recognized",
            payload={"task_type": task_type, "task_type_label": task_type_label, "modules": modules},
        )

    async def emit_context_retrieved(self, doc_count: int, summary: str):
        await self.emit(
            "context.retrieved",
            payload={"doc_count": doc_count, "summary": summary},
        )

    async def emit_module_started(self, agent_id: str, agent_name: str):
        await self.emit("module.started", agent_id=agent_id, agent_name=agent_name,
                        payload={"message": f"{agent_name} 开始分析..."})

    async def emit_module_completed(self, agent_id: str, agent_name: str, summary: str):
        await self.emit("module.completed", agent_id=agent_id, agent_name=agent_name,
                        payload={"summary": summary})

    async def emit_module_failed(self, agent_id: str, agent_name: str, error: str):
        await self.emit("module.failed", agent_id=agent_id, agent_name=agent_name,
                        payload={"error": error})

    async def emit_feishu_writing(self, asset_type: str):
        await self.emit("feishu.writing", payload={"asset_type": asset_type,
                                                    "message": f"正在创建飞书{asset_type}..."})

    async def emit_task_done(self, summary: str):
        await self.emit("task.done", payload={"summary": summary,
                                               "message": "执行完成，结果已准备好"})

    async def emit_task_error(self, reason: str):
        await self.emit("task.error", payload={"reason": reason,
                                                "message": f"执行出错：{reason}"})
