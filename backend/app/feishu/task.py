"""飞书任务：创建任务"""
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from lark_oapi.api.task.v2 import (
    CreateTaskRequest,
    InputTask,
    Member,
    Due,
)

from app.feishu.client import get_applink_base_url, get_feishu_client
from app.feishu.retry import with_retry

logger = logging.getLogger(__name__)


def _parse_action_item(text: str) -> dict:
    """Extract due date and assignee hint from action item text."""
    result = {"summary": text, "due": None, "assignee_hint": None}

    # Extract due date patterns: 截止 YYYY-MM-DD or 截止 MM/DD or 本周/本月
    date_match = re.search(r'截止[：:]?\s*(\d{4}-\d{2}-\d{2})', text)
    if date_match:
        result["due"] = date_match.group(1)

    # Extract assignee: 负责人[：:]\s*(\S+)
    assignee_match = re.search(r'负责人[：:]?\s*([^\s，,）)]+)', text)
    if assignee_match:
        result["assignee_hint"] = assignee_match.group(1)

    # Clean the summary: strip the parenthetical metadata
    summary = re.sub(r'[（(][^）)]*[）)]', '', text).strip()
    result["summary"] = summary or text

    return result


def _due_to_timestamp_ms(due: Optional[str]) -> Optional[int]:
    if not due:
        return None
    try:
        due_dt = datetime.strptime(due, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        logger.warning(f"无法解析任务截止日期: {due}")
        return None
    return int(due_dt.timestamp() * 1000)


async def create_task(title: str, notes: Optional[str] = None, due_ms: Optional[int] = None) -> dict:
    return await with_retry(_create_task_impl, title, notes, due_ms)


async def _create_task_impl(title: str, notes: Optional[str] = None, due_ms: Optional[int] = None) -> dict:
    """创建飞书任务，返回 {"task_guid": "...", "url": "..."}
    优先使用 user_access_token（任务归属当前用户可见），无授权时降级为 tenant_access_token。
    """
    import lark_oapi as lark
    from app.feishu.user_token import get_user_access_token, get_user_open_id

    client = get_feishu_client()
    user_token = get_user_access_token()
    user_open_id = get_user_open_id()

    task_builder = InputTask.builder().summary(title)
    if notes:
        task_builder = task_builder.description(notes[:1000])
    if due_ms:
        due = Due.builder().timestamp(str(due_ms)).is_all_day(False).build()
        task_builder = task_builder.due(due)
    # 将授权用户设为负责人，使任务出现在「我负责的」列表并可通过 AppLink 打开
    if user_open_id:
        member = Member.builder().id(user_open_id).type("user").role("assignee").build()
        task_builder = task_builder.members([member])

    req = CreateTaskRequest.builder().request_body(task_builder.build()).build()

    if user_token:
        option = lark.RequestOption.builder().user_access_token(user_token).build()
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.task.v2.task.create, req, option),
            timeout=30.0,
        )
    else:
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.task.v2.task.create, req),
            timeout=30.0,
        )

    if not resp.success():
        raise RuntimeError(f"创建任务失败: {resp.msg}")

    task_guid = resp.data.task.guid
    url = f"{get_applink_base_url()}/client/todo/detail?guid={task_guid}"
    logger.info(f"飞书任务创建成功: {task_guid} (用户token={'有' if user_token else '无'})")
    return {"task_guid": task_guid, "url": url, "title": title}


async def batch_create_tasks(items: list[str]) -> list[dict]:
    return await _batch_create_tasks_impl(items)


async def _batch_create_tasks_impl(items: list[str]) -> list[dict]:
    """批量创建任务列表"""
    results = []
    errors = []
    for item in items[:20]:   # 最多 20 个
        try:
            parsed = _parse_action_item(item)
            notes = None
            if parsed["assignee_hint"]:
                notes = f"负责人：{parsed['assignee_hint']}"
            result = await create_task(
                title=parsed["summary"],
                notes=notes,
                due_ms=_due_to_timestamp_ms(parsed["due"]),
            )
            if parsed["assignee_hint"]:
                result["assignee_hint"] = parsed["assignee_hint"]
            results.append(result)
        except Exception as e:
            logger.warning(f"创建任务失败: {item} - {e}")
            errors.append(f"{item}: {e}")
    if errors:
        raise RuntimeError("部分飞书任务创建失败: " + "；".join(errors[:3]))
    return results
