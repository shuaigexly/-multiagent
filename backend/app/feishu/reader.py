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

from app.core.redaction import redact_sensitive_text
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)


class FeishuReaderError(RuntimeError):
    """Raised when Feishu data could not be read; distinct from an empty result."""


def _response_error(action: str, resp) -> FeishuReaderError:
    msg = redact_sensitive_text(getattr(resp, "msg", ""), max_chars=500)
    return FeishuReaderError(f"{action}失败: {msg} (code={getattr(resp, 'code', '')})")


def _wrap_reader_exception(action: str, exc: Exception) -> FeishuReaderError:
    if isinstance(exc, FeishuReaderError):
        return exc
    return FeishuReaderError(f"{action}异常: {redact_sensitive_text(exc, max_chars=500)}")


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


def _page_token(data) -> str | None:
    if data is None:
        return None
    return getattr(data, "page_token", None) or getattr(data, "next_page_token", None)


async def _list_all_pages(
    *,
    action: str,
    call,
    build_request,
    option=None,
    item_attr: str = "items",
    timeout: float = 30.0,
) -> list:
    items: list = []
    page_token: str | None = None
    while True:
        req = build_request(page_token)
        if option is None:
            resp = await asyncio.wait_for(asyncio.to_thread(call, req), timeout=timeout)
        else:
            resp = await asyncio.wait_for(asyncio.to_thread(call, req, option), timeout=timeout)
        if not resp.success():
            logger.error(
                "%s failed: %s (code=%s)",
                action,
                redact_sensitive_text(resp.msg, max_chars=500),
                resp.code,
            )
            raise _response_error(action, resp)
        data = resp.data
        items.extend(getattr(data, item_attr, None) or [])
        if not getattr(data, "has_more", False):
            return items
        page_token = _page_token(data)
        if not page_token:
            raise FeishuReaderError(f"{action} failed: has_more=true but page_token missing")


def _finish_paged_builder(builder, page_token: str | None):
    if page_token:
        page_token_method = getattr(builder, "page_token", None)
        if page_token_method is None:
            raise FeishuReaderError("Feishu SDK builder does not support page_token")
        page_token_method(page_token)
    return builder.build()


async def list_drive_files(page_size: int = 20) -> list[dict]:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token

        client = get_feishu_client()
        user_token = get_user_access_token()
        option = lark.RequestOption.builder().user_access_token(user_token).build() if user_token else None

        def _build(page_token: str | None):
            return _finish_paged_builder(ListFileRequest.builder().page_size(page_size), page_token)

        files = await _list_all_pages(
            action="list drive files",
            call=client.drive.v1.file.list,
            build_request=_build,
            option=option,
            item_attr="files",
        )
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
        logger.error("read drive files failed: %s", redact_sensitive_text(e, max_chars=500))
        raise _wrap_reader_exception("read drive files", e) from e


async def list_wiki_spaces(page_size: int = 20) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()

        def _build(page_token: str | None):
            return _finish_paged_builder(ListSpaceRequest.builder().page_size(page_size), page_token)

        spaces = await _list_all_pages(
            action="list wiki spaces",
            call=client.wiki.v2.space.list,
            build_request=_build,
        )
        return [
            {
                "space_id": item.space_id,
                "name": item.name,
                "description": item.description,
            }
            for item in spaces
        ]
    except Exception as e:
        logger.error("read wiki spaces failed: %s", redact_sensitive_text(e, max_chars=500))
        raise _wrap_reader_exception("read wiki spaces", e) from e


async def list_wiki_nodes(space_id: str, page_size: int = 50) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()

        def _build(page_token: str | None):
            builder = ListSpaceNodeRequest.builder().space_id(space_id).page_size(page_size)
            return _finish_paged_builder(builder, page_token)

        nodes = await _list_all_pages(
            action="list wiki nodes",
            call=client.wiki.v2.space_node.list,
            build_request=_build,
        )
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
        logger.error(
            "read wiki nodes failed space_id=%s: %s",
            space_id,
            redact_sensitive_text(e, max_chars=500),
        )
        raise _wrap_reader_exception("read wiki nodes", e) from e


async def list_chats(page_size: int = 20) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()

        def _build(page_token: str | None):
            return _finish_paged_builder(ListChatRequest.builder().page_size(page_size), page_token)

        chats = await _list_all_pages(
            action="list chats",
            call=client.im.v1.chat.list,
            build_request=_build,
        )
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
        logger.error("read chats failed: %s", redact_sensitive_text(e, max_chars=500))
        raise _wrap_reader_exception("read chats", e) from e


async def list_chat_messages(chat_id: str, page_size: int = 20) -> list[dict]:
    try:
        from app.feishu.client import get_feishu_client

        client = get_feishu_client()

        def _build(page_token: str | None):
            builder = (
                ListMessageRequest.builder()
                .container_id(chat_id)
                .container_id_type("chat")
                .page_size(page_size)
            )
            return _finish_paged_builder(builder, page_token)

        messages = await _list_all_pages(
            action="list chat messages",
            call=client.im.v1.message.list,
            build_request=_build,
        )
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
        logger.error(
            "read chat messages failed chat_id=%s: %s",
            chat_id,
            redact_sensitive_text(e, max_chars=500),
        )
        raise _wrap_reader_exception("read chat messages", e) from e


async def list_calendar_events(start_time: str, end_time: str, page_size: int = 50) -> list[dict]:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token

        client = get_feishu_client()
        user_token = get_user_access_token()
        option = lark.RequestOption.builder().user_access_token(user_token).build() if user_token else None

        def _build(page_token: str | None):
            builder = (
                ListCalendarEventRequest.builder()
                .calendar_id("primary")
                .start_time(start_time)
                .end_time(end_time)
                .page_size(page_size)
            )
            return _finish_paged_builder(builder, page_token)

        events = await _list_all_pages(
            action="list calendar events",
            call=client.calendar.v4.calendar_event.list,
            build_request=_build,
            option=option,
        )
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
        logger.error("read calendar events failed: %s", redact_sensitive_text(e, max_chars=500))
        raise _wrap_reader_exception("read calendar events", e) from e


async def list_tasks(page_size: int = 50) -> list[dict]:
    try:
        import lark_oapi as lark
        from app.feishu.client import get_feishu_client
        from app.feishu.user_token import get_user_access_token, set_user_access_token

        user_token = get_user_access_token()
        if not user_token:
            raise FeishuReaderError("Feishu task API requires user OAuth authorization")

        client = get_feishu_client()
        option = lark.RequestOption.builder().user_access_token(user_token).build()

        def _build(page_token: str | None):
            return _finish_paged_builder(ListTaskRequest.builder().page_size(page_size), page_token)

        try:
            tasks = await _list_all_pages(
                action="list tasks",
                call=client.task.v2.task.list,
                build_request=_build,
                option=option,
            )
        except FeishuReaderError as exc:
            if "99991668" in str(exc):
                set_user_access_token(None)
                raise FeishuReaderError("Feishu user token expired; please authorize again") from exc
            raise

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
        logger.error("read tasks failed: %s", redact_sensitive_text(e, max_chars=500))
        raise _wrap_reader_exception("read tasks", e) from e


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
            logger.error(
                "读取文档内容失败: %s (code=%s)",
                redact_sensitive_text(resp.msg, max_chars=500),
                resp.code,
            )
            raise _response_error("读取文档内容", resp)
        return resp.data.content if resp.data and resp.data.content else ""
    except Exception as e:
        logger.error(
            "读取文档内容异常(%s): %s",
            redact_sensitive_text(f"document_token={document_id}"),
            redact_sensitive_text(e, max_chars=500),
        )
        raise _wrap_reader_exception("读取文档内容", e) from e
