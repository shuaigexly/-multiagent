"""飞书数据读取：文件、知识库、群聊、日历、任务、文档内容"""
import asyncio
import json
import logging

from lark_oapi.api.calendar.v4 import ListCalendarEventRequest
from lark_oapi.api.docx.v1 import RawContentDocumentRequest
from lark_oapi.api.drive.v1 import ListFileRequest
from lark_oapi.api.im.v1 import ListChatRequest, ListMessageRequest
from lark_oapi.api.task.v2 import ListTaskRequest
from lark_oapi.api.wiki.v2 import ListSpaceNodeRequest, ListSpaceRequest

from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)


class FeishuReaderError(RuntimeError):
    """Raised when Feishu data could not be read; distinct from an empty result."""


def _response_error(action: str, resp) -> FeishuReaderError:
    return FeishuReaderError(f"{action}失败: {getattr(resp, 'msg', '')} (code={getattr(resp, 'code', '')})")


def _wrap_reader_exception(action: str, exc: Exception) -> FeishuReaderError:
    if isinstance(exc, FeishuReaderError):
        return exc
    return FeishuReaderError(f"{action}异常: {exc}")


def _ts_to_readable(ts) -> str | None:
    """Convert Feishu timestamp (seconds as string/int) to readable datetime string."""
    if ts is None:
        return None
    try:
        from datetime import datetime, timezone

        ts_int = int(ts)
        return datetime.fromtimestamp(ts_int, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError, OSError):
        return str(ts)


def _message_preview(content: str | None) -> str:
    if not content:
        return ""
    try:
        parsed = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return truncate_with_marker(content, 200)

    if isinstance(parsed, dict):
        for key in ("text", "title", "content"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return truncate_with_marker(value, 200)
    return truncate_with_marker(json.dumps(parsed, ensure_ascii=False), 200)


async def list_drive_files(page_size: int = 20) -> list[dict]:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token

        client = get_feishu_client()
        req = ListFileRequest.builder().page_size(page_size).build()
        user_token = get_user_access_token()
        if user_token:
            option = lark.RequestOption.builder().user_access_token(user_token).build()
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.drive.v1.file.list, req, option),
                timeout=30.0,
            )
        else:
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.drive.v1.file.list, req),
                timeout=30.0,
        )
        if not resp.success():
            logger.error(f"列出飞书云盘文件失败: {resp.msg} (code={resp.code})")
            raise _response_error("列出飞书云盘文件", resp)

        files = resp.data.files if resp.data and resp.data.files else []
        return [
            {
                "token": item.token,
                "name": item.name,
                "type": item.type,
                "url": item.url,
                "created_time": _ts_to_readable(item.created_time),
                "modified_time": _ts_to_readable(item.modified_time),
            }
            for item in files
        ]
    except Exception as e:
        logger.error(f"读取飞书云盘文件异常: {e}", exc_info=True)
        raise _wrap_reader_exception("读取飞书云盘文件", e) from e


async def list_wiki_spaces(page_size: int = 20) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()
        req = ListSpaceRequest.builder().page_size(page_size).build()
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.wiki.v2.space.list, req),
            timeout=30.0,
        )
        if not resp.success():
            logger.error(f"列出知识库空间失败: {resp.msg} (code={resp.code})")
            raise _response_error("列出知识库空间", resp)

        spaces = resp.data.items if resp.data and resp.data.items else []
        return [
            {
                "space_id": item.space_id,
                "name": item.name,
                "description": item.description,
            }
            for item in spaces
        ]
    except Exception as e:
        logger.error(f"读取知识库空间异常: {e}", exc_info=True)
        raise _wrap_reader_exception("读取知识库空间", e) from e


async def list_wiki_nodes(space_id: str, page_size: int = 50) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()
        req = (
            ListSpaceNodeRequest.builder()
            .space_id(space_id)
            .page_size(page_size)
            .build()
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.wiki.v2.space_node.list, req),
            timeout=30.0,
        )
        if not resp.success():
            logger.error(f"列出知识库节点失败: {resp.msg} (code={resp.code})")
            raise _response_error("列出知识库节点", resp)

        nodes = resp.data.items if resp.data and resp.data.items else []
        return [
            {
                "node_token": item.node_token,
                "title": item.title,
                "obj_type": item.obj_type,
                "obj_token": item.obj_token,
                "parent_node_token": item.parent_node_token,
            }
            for item in nodes
        ]
    except Exception as e:
        logger.error(f"读取知识库节点异常: {e}", exc_info=True)
        raise _wrap_reader_exception("读取知识库节点", e) from e


async def list_chats(page_size: int = 20) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()
        req = ListChatRequest.builder().page_size(page_size).build()
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.im.v1.chat.list, req),
            timeout=30.0,
        )
        if not resp.success():
            logger.error(f"列出群聊失败: {resp.msg} (code={resp.code})")
            raise _response_error("列出群聊", resp)

        chats = resp.data.items if resp.data and resp.data.items else []
        return [
            {
                "chat_id": item.chat_id,
                "name": item.name,
                "description": item.description,
                "chat_type": getattr(item, "chat_type", "") or "",
            }
            for item in chats
        ]
    except Exception as e:
        logger.error(f"读取群聊列表异常: {e}", exc_info=True)
        raise _wrap_reader_exception("读取群聊列表", e) from e


async def list_chat_messages(chat_id: str, page_size: int = 20) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()
        req = (
            ListMessageRequest.builder()
            .container_id(chat_id)
            .container_id_type("chat")
            .page_size(page_size)
            .build()
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.im.v1.message.list, req),
            timeout=30.0,
        )
        if not resp.success():
            logger.error(f"列出群消息失败: {resp.msg} (code={resp.code})")
            raise _response_error("列出群消息", resp)

        messages = resp.data.items if resp.data and resp.data.items else []
        return [
            {
                "message_id": item.message_id,
                "sender_id": item.sender.id if item.sender else None,
                "create_time": item.create_time,
                "content_type": item.msg_type,
                "content_preview": _message_preview(item.body.content if item.body else None),
            }
            for item in messages
        ]
    except Exception as e:
        logger.error(f"读取群消息异常(chat_id={chat_id}): {e}", exc_info=True)
        raise _wrap_reader_exception("读取群消息", e) from e


async def list_calendar_events(start_time: str, end_time: str, page_size: int = 50) -> list[dict]:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token

        client = get_feishu_client()
        req = (
            ListCalendarEventRequest.builder()
            .calendar_id("primary")
            .start_time(start_time)
            .end_time(end_time)
            .page_size(page_size)
            .build()
        )
        user_token = get_user_access_token()
        if user_token:
            option = lark.RequestOption.builder().user_access_token(user_token).build()
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.calendar.v4.calendar_event.list, req, option),
                timeout=30.0,
            )
        else:
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.calendar.v4.calendar_event.list, req),
                timeout=30.0,
        )
        if not resp.success():
            logger.error(f"列出日历事件失败: {resp.msg} (code={resp.code})")
            raise _response_error("列出日历事件", resp)

        events = resp.data.items if resp.data and resp.data.items else []
        return [
            {
                "event_id": item.event_id,
                "summary": item.summary,
                "start_time": _ts_to_readable(item.start_time.timestamp) if item.start_time else None,
                "end_time": _ts_to_readable(item.end_time.timestamp) if item.end_time else None,
                "attendees_count": len(item.attendees or []),
                "location": item.location.name if item.location else "",
                "description": item.description,
            }
            for item in events
        ]
    except Exception as e:
        logger.error(f"读取日历事件异常: {e}", exc_info=True)
        raise _wrap_reader_exception("读取日历事件", e) from e


async def list_tasks(page_size: int = 50) -> list[dict]:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token, set_user_access_token

        user_token = get_user_access_token()
        if not user_token:
            logger.info("飞书任务 API 需要用户授权，请在「设置」页面点击「授权飞书任务」")
            raise FeishuReaderError("飞书任务 API 需要用户授权")

        client = get_feishu_client()
        req = ListTaskRequest.builder().page_size(page_size).build()
        option = lark.RequestOption.builder().user_access_token(user_token).build()
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.task.v2.task.list, req, option),
            timeout=30.0,
        )
        if not resp.success():
            if resp.code == 99991668:
                logger.warning("飞书用户 token 已过期，请重新授权（code=99991668）")
                set_user_access_token(None)  # 清除过期 token
                raise FeishuReaderError("飞书用户 token 已过期，请重新授权")
            else:
                logger.error(f"列出任务失败: {resp.msg} (code={resp.code})")
                raise _response_error("列出任务", resp)

        tasks = resp.data.items if resp.data and resp.data.items else []
        return [
            {
                "guid": item.guid,
                "summary": item.summary,
                "due": _ts_to_readable(item.due.timestamp) if item.due and item.due.timestamp is not None else None,
                "status": item.status,
                "completed": bool(item.completed_at),
                "creator_id": item.creator.id if item.creator else None,
                "assignees": [assignee.id for assignee in (item.assignee_related or []) if assignee.id],
            }
            for item in tasks
        ]
    except Exception as e:
        logger.error(f"读取任务列表异常: {e}", exc_info=True)
        raise _wrap_reader_exception("读取任务列表", e) from e


async def read_doc_content(document_id: str) -> str:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token

        client = get_feishu_client()
        req = RawContentDocumentRequest.builder().document_id(document_id).build()
        user_token = get_user_access_token()
        if user_token:
            option = lark.RequestOption.builder().user_access_token(user_token).build()
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.docx.v1.document.raw_content, req, option),
                timeout=30.0,
            )
        else:
            resp = await asyncio.wait_for(
                asyncio.to_thread(client.docx.v1.document.raw_content, req),
                timeout=30.0,
            )
        if not resp.success():
            logger.error(f"读取文档内容失败: {resp.msg} (code={resp.code})")
            raise _response_error("读取文档内容", resp)
        return resp.data.content if resp.data and resp.data.content else ""
    except Exception as e:
        logger.error(f"读取文档内容异常(document_id={document_id}): {e}", exc_info=True)
        raise _wrap_reader_exception("读取文档内容", e) from e
