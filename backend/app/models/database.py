from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON,
    create_engine, event, UniqueConstraint, Index, inspect, text
)
from sqlalchemy import event as sa_event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import uuid

from app.core.settings import settings


def generate_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=generate_id)
    status = Column(String, nullable=False, default="pending")   # pending/planning/running/done/failed
    input_text = Column(Text, nullable=True)
    input_file = Column(String, nullable=True)           # uploaded file path
    task_type = Column(String, nullable=True)            # TaskPlanner 识别结果
    task_type_label = Column(String, nullable=True)      # 中文标签
    selected_modules = Column(JSON, nullable=True)       # list[str]
    user_instructions = Column(Text, nullable=True)
    feishu_context = Column(JSON, nullable=True)         # 关联飞书资产
    result_summary = Column(Text, nullable=True)         # 最终汇总结论
    error_message = Column(Text, nullable=True)
    last_sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        UniqueConstraint("task_id", "sequence", name="uq_task_event_seq"),
        Index("ix_task_events_task_id_seq", "task_id", "sequence"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)   # task.recognized / module.started / etc.
    agent_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class TaskResult(Base):
    __tablename__ = "task_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False)
    agent_name = Column(String, nullable=False)
    sections = Column(JSON, nullable=True)       # list[{title, content}]
    action_items = Column(JSON, nullable=True)   # list[str]
    chart_data = Column(JSON, nullable=True)     # list[dict]
    raw_output = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PublishedAsset(Base):
    __tablename__ = "published_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    asset_type = Column(String, nullable=False)   # doc/bitable/message/task/calendar/wiki
    title = Column(String, nullable=True)
    feishu_url = Column(String, nullable=True)
    feishu_id = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class UserConfig(Base):
    __tablename__ = "user_config"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AuditLog(Base):
    """Append-only 审计日志：记录敏感操作 who / what / when / outcome。"""
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_action_created", "action", "created_at"),
        Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(64), nullable=False)
    actor = Column(String(128), nullable=False, default="system")
    target = Column(String(256), nullable=False, default="")
    tenant_id = Column(String(64), nullable=False, default="")
    correlation_id = Column(String(64), nullable=False, default="")
    payload = Column(JSON, nullable=True)
    result = Column(String(32), nullable=False, default="ok")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AgentMemory(Base):
    """Agent 长期记忆 — 跨任务召回相似案例 + 自我反思。

    kind:
      'case'       一次任务的输出摘要（默认）
      'reflection' agent 在任务后自评的"我学到了什么"
    """
    __tablename__ = "agent_memory"
    __table_args__ = (
        Index("ix_agent_memory_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_agent_memory_kind", "kind"),
        Index("ix_agent_memory_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, default="default")
    agent_id = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False, default="case")
    task_hash = Column(String(64), nullable=False)
    task_text = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    embedding_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AgentPromptHint(Base):
    """Prompt 自演化 — 把高质量反思 promote 为 system_prompt 注入条目。

    base_agent._call_llm 启动时按 (tenant_id, agent_id, active=True) 拉取条目，
    拼到 SYSTEM_PROMPT 末尾。每个 (tenant, agent) 最多 _MAX_HINTS 条，超出 FIFO 替换。
    """
    __tablename__ = "agent_prompt_hint"
    __table_args__ = (
        Index("ix_agent_prompt_hint_tenant_agent", "tenant_id", "agent_id", "active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, default="default")
    agent_id = Column(String(64), nullable=False)
    rule_text = Column(Text, nullable=False)         # 提炼后的规则（1-2 句，祈使句）
    source_summary = Column(Text, nullable=False)    # 来源 reflection 原文
    score = Column(Integer, nullable=False, default=0)  # 0-10 LLM-judge 分
    active = Column(Integer, nullable=False, default=1)  # 1/0 — 软删除
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class FeishuBotEvent(Base):
    __tablename__ = "feishu_bot_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_message_id: Mapped[str] = mapped_column(String(128))
    chat_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    open_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


# Async engine
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=_connect_args,
)


if settings.database_url.startswith("sqlite"):
    @sa_event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def _ensure_task_user_instructions_column(conn):
    def has_column(sync_conn) -> bool:
        inspector = inspect(sync_conn)
        return any(
            column["name"] == "user_instructions"
            for column in inspector.get_columns("tasks")
        )

    if not await conn.run_sync(has_column):
        from sqlalchemy.exc import OperationalError
        try:
            await conn.execute(text("ALTER TABLE tasks ADD COLUMN user_instructions TEXT"))
        except OperationalError as exc:
            if "duplicate column" not in str(exc).lower():
                raise


async def _ensure_column(conn, table_name: str, column_name: str, ddl_type: str, default: str = ""):
    """通用幂等 ALTER ADD COLUMN — create_all 不会给已存在表加新列，需手动迁移。"""
    def has_column(sync_conn) -> bool:
        inspector = inspect(sync_conn)
        try:
            cols = inspector.get_columns(table_name)
        except Exception:
            return True  # 表本身不存在 → create_all 会建好整张表（含此列），无需 ALTER
        return any(c["name"] == column_name for c in cols)

    if await conn.run_sync(has_column):
        return
    from sqlalchemy.exc import OperationalError
    suffix = f" DEFAULT {default}" if default else ""
    try:
        await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl_type}{suffix}"))
    except OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_task_user_instructions_column(conn)
        # v7.5+ 幂等迁移：旧库已存在 agent_memory 表时 create_all 不会加 kind 列
        await _ensure_column(conn, "agent_memory", "kind", "VARCHAR(32)", default="'case'")


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
