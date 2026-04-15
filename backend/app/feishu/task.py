"""飞书任务：创建任务"""
import logging
from typing import Optional

from lark_oapi.api.task.v2 import (
    CreateTaskRequest,
    CreateTaskRequestBody,
    InputTask,
    UndoneTaskDueTime,
)

from app.feishu.client import get_feishu_client

logger = logging.getLogger(__name__)


async def create_task(title: str, notes: Optional[str] = None, due_ms: Optional[int] = None) -> dict:
    """创建飞书任务，返回 {"task_guid": "...", "url": "..."}"""
    client = get_feishu_client()

    task_builder = InputTask.builder().summary(title)
    if notes:
        task_builder = task_builder.description(notes[:1000])
    if due_ms:
        due = UndoneTaskDueTime.builder().timestamp(str(due_ms)).is_all_day(False).build()
        task_builder = task_builder.due(due)

    req_body = CreateTaskRequestBody.builder().task(task_builder.build()).build()
    req = CreateTaskRequest.builder().request_body(req_body).build()
    resp = client.task.v2.task.create(req)
    if not resp.success():
        raise RuntimeError(f"创建任务失败: {resp.msg}")

    task_guid = resp.data.task.guid
    url = f"https://applink.feishu.cn/client/todo/detail?guid={task_guid}"
    logger.info(f"飞书任务创建成功: {task_guid}")
    return {"task_guid": task_guid, "url": url, "title": title}


async def batch_create_tasks(items: list[str]) -> list[dict]:
    """批量创建任务列表"""
    results = []
    for item in items[:20]:   # 最多 20 个
        try:
            result = await create_task(title=item)
            results.append(result)
        except Exception as e:
            logger.warning(f"创建任务失败: {item} - {e}")
    return results
