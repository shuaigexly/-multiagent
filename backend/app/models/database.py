from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON,
    create_engine, event, UniqueConstraint
)
from sqlalchemy import event as sa_event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
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
    feishu_context = Column(JSON, nullable=True)         # 关联飞书资产
    result_summary = Column(Text, nullable=True)         # 最终汇总结论
    error_message = Column(Text, nullable=True)
    last_sequence = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("task_id", "sequence", name="uq_task_event_seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)   # task.recognized / module.started / etc.
    agent_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TaskResult(Base):
    __tablename__ = "task_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    agent_id = Column(String, nullable=False)
    agent_name = Column(String, nullable=False)
    sections = Column(JSON, nullable=True)       # list[{title, content}]
    action_items = Column(JSON, nullable=True)   # list[str]
    raw_output = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PublishedAsset(Base):
    __tablename__ = "published_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, nullable=False, index=True)
    asset_type = Column(String, nullable=False)   # doc/bitable/message/task/calendar/wiki
    title = Column(String, nullable=True)
    feishu_url = Column(String, nullable=True)
    feishu_id = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# Async engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
)


@sa_event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragmas(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
