"""飞书上下文读取 API"""
import asyncio
import time

from fastapi import APIRouter, Depends, Query

from app.core.auth import require_api_key
from app.feishu.reader import (
    FeishuReaderError,
    list_calendar_events,
    list_chat_messages,
    list_chats,
    list_drive_files,
    list_tasks,
    list_wiki_nodes,
    list_wiki_spaces,
    read_doc_content,
)

router = APIRouter(
    prefix="/api/v1/feishu",
    tags=["feishu-context"],
    dependencies=[Depends(require_api_key)],
)


def _default_calendar_range() -> tuple[str, str]:
    start = int(time.time())
    end = start + 7 * 24 * 60 * 60
    return str(start), str(end)


def _empty_list_error(exc: Exception) -> dict:
    return {"data": [], "total": 0, "error": str(exc)}


@router.get("/drive")
async def get_drive_files(page_size: int = Query(20, ge=1, le=200)):
    try:
        data = await list_drive_files(page_size=page_size)
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/wiki/spaces")
async def get_wiki_spaces(page_size: int = Query(20, ge=1, le=200)):
    try:
        data = await list_wiki_spaces(page_size=page_size)
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/wiki/nodes/{space_id}")
async def get_wiki_nodes(space_id: str, page_size: int = Query(50, ge=1, le=200)):
    try:
        data = await list_wiki_nodes(space_id=space_id, page_size=page_size)
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/chats")
async def get_chats(page_size: int = Query(20, ge=1, le=200)):
    try:
        data = await list_chats(page_size=page_size)
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/chats/{chat_id}/messages")
async def get_chat_messages(chat_id: str, page_size: int = Query(20, ge=1, le=200)):
    try:
        data = await list_chat_messages(chat_id=chat_id, page_size=page_size)
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/calendar")
async def get_calendar_events(
    start: str | None = Query(None),
    end: str | None = Query(None),
    page_size: int = Query(50, ge=1, le=200),
):
    default_start, default_end = _default_calendar_range()
    try:
        data = await list_calendar_events(
            start_time=start or default_start,
            end_time=end or default_end,
            page_size=page_size,
        )
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/tasks")
async def get_tasks(page_size: int = Query(50, ge=1, le=200)):
    try:
        data = await list_tasks(page_size=page_size)
        return {"data": data, "total": len(data)}
    except FeishuReaderError as exc:
        return _empty_list_error(exc)


@router.get("/doc/{token}/content")
async def get_doc_content(token: str):
    try:
        content = await read_doc_content(token)
        return {"content": content}
    except FeishuReaderError as exc:
        return {"content": "", "error": str(exc)}


@router.get("/context")
async def get_feishu_context():
    start, end = _default_calendar_range()
    drive, calendar, tasks = await asyncio.gather(
        list_drive_files(page_size=10),
        list_calendar_events(start_time=start, end_time=end, page_size=50),
        list_tasks(page_size=20),
        return_exceptions=True,
    )
    errors = {}
    # v8.1 修复：CancelledError 在 Python 3.8+ 继承自 BaseException 而不是 Exception，
    # isinstance(x, Exception) 会漏匹配 → 客户端断连时 cancelled 对象被当 drive 数据返回，
    # 后续 JSON 序列化炸（无法序列化 CancelledError 实例）。改用 BaseException 全覆盖。
    if isinstance(drive, BaseException):
        if isinstance(drive, asyncio.CancelledError):
            raise drive
        errors["drive"] = str(drive)
        drive = []
    if isinstance(calendar, BaseException):
        if isinstance(calendar, asyncio.CancelledError):
            raise calendar
        errors["calendar"] = str(calendar)
        calendar = []
    if isinstance(tasks, BaseException):
        if isinstance(tasks, asyncio.CancelledError):
            raise tasks
        errors["tasks"] = str(tasks)
        tasks = []
    pending_tasks = [item for item in tasks if not item.get("completed")][:20]
    payload = {
        "drive": drive,
        "calendar": calendar,
        "tasks": pending_tasks,
    }
    if errors:
        payload["errors"] = errors
    return payload
