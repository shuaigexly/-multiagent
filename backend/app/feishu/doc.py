"""飞书文档：创建文档，写入内容"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    Block,
    Callout,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentResponse,
    Divider,
    Text,
    TextElement,
    TextRun,
)

from app.agents.base_agent import AgentResult
from app.feishu.client import get_feishu_base_url, get_feishu_client
from app.feishu.retry import with_retry

logger = logging.getLogger(__name__)

MAX_DOC_TEXT_LENGTH = 2000
MAX_BLOCKS_PER_REQUEST = 40
PLAIN_TEXT_BLOCK_TYPE = 2
HEADING1_BLOCK_TYPE = 3
HEADING2_BLOCK_TYPE = 4
HEADING3_BLOCK_TYPE = 5
BULLET_BLOCK_TYPE = 12
ORDERED_BLOCK_TYPE = 13
CALLOUT_BLOCK_TYPE = 19
DIVIDER_BLOCK_TYPE = 22

_BLOCK_ATTRS = {
    PLAIN_TEXT_BLOCK_TYPE: "text",
    HEADING1_BLOCK_TYPE: "heading1",
    HEADING2_BLOCK_TYPE: "heading2",
    HEADING3_BLOCK_TYPE: "heading3",
    BULLET_BLOCK_TYPE: "bullet",
    ORDERED_BLOCK_TYPE: "ordered",
}
_LIST_PREFIX_RE = re.compile(r"^[-*•\d\.\)、\s]+")


@dataclass(slots=True)
class RichBlockSpec:
    block: Block
    child_blocks: list[Block] = field(default_factory=list)


async def create_document(title: str, content: str, folder_token: Optional[str] = None) -> dict:
    return await with_retry(_create_document_impl, title, content, folder_token)


async def create_structured_document(
    title: str,
    block_specs: Sequence[RichBlockSpec],
    folder_token: Optional[str] = None,
) -> dict:
    return await with_retry(_create_structured_document_impl, title, list(block_specs), folder_token)


async def create_rich_document(
    title: str,
    agent_results: list[AgentResult],
    folder_token: Optional[str] = None,
) -> dict:
    block_specs = _build_agent_block_specs(agent_results)
    return await create_structured_document(title=title, block_specs=block_specs, folder_token=folder_token)


def build_heading_block(level: int, text: str) -> Block:
    block_type = {
        1: HEADING1_BLOCK_TYPE,
        2: HEADING2_BLOCK_TYPE,
        3: HEADING3_BLOCK_TYPE,
    }[level]
    return _build_text_block(block_type, text)


def build_text_block(text: str) -> Block:
    return _build_text_block(PLAIN_TEXT_BLOCK_TYPE, text)


def build_bullet_block(text: str) -> Block:
    return _build_text_block(BULLET_BLOCK_TYPE, text)


def build_ordered_block(text: str) -> Block:
    return _build_text_block(ORDERED_BLOCK_TYPE, text)


def build_divider_block() -> Block:
    return (
        Block.builder()
        .block_type(DIVIDER_BLOCK_TYPE)
        .divider(Divider.builder().build())
        .build()
    )


def build_callout_block() -> Block:
    return (
        Block.builder()
        .block_type(CALLOUT_BLOCK_TYPE)
        .callout(Callout.builder().build())
        .build()
    )


async def _create_document_impl(title: str, content: str, folder_token: Optional[str] = None) -> dict:
    """
    创建飞书文档，写入标题和内容。
    返回 {"doc_token": "...", "url": "..."}
    """
    client = get_feishu_client()
    doc_token = await _create_document_shell(title, client, folder_token)
    await _append_text_blocks(client, doc_token, content)
    return _build_document_result(title, doc_token)


async def _create_structured_document_impl(
    title: str,
    block_specs: list[RichBlockSpec],
    folder_token: Optional[str] = None,
) -> dict:
    client = get_feishu_client()
    doc_token = await _create_document_shell(title, client, folder_token)
    await _append_rich_blocks(doc_token, block_specs, client)
    return _build_document_result(title, doc_token)


async def _create_document_shell(
    title: str,
    client: lark.Client,
    folder_token: Optional[str] = None,
) -> str:
    if folder_token:
        logger.info("当前文档创建流程暂未处理 folder_token=%s", folder_token)

    req_body = CreateDocumentRequestBody.builder().title(title).build()
    req = CreateDocumentRequest.builder().request_body(req_body).build()

    resp: CreateDocumentResponse = await asyncio.to_thread(client.docx.v1.document.create, req)
    if not resp.success():
        raise RuntimeError(f"创建飞书文档失败: {resp.msg} (code={resp.code})")

    doc_token = resp.data.document.document_id
    logger.info("飞书文档创建成功: %s", doc_token)
    return doc_token


def _build_document_result(title: str, doc_token: str) -> dict:
    url = f"{get_feishu_base_url()}/docx/{doc_token}"
    return {"doc_token": doc_token, "url": url, "title": title}


async def _append_text_blocks(client: lark.Client, doc_token: str, content: str) -> None:
    """将内容按段落追加到文档"""
    paragraphs = content.split("\n\n")
    blocks = []
    for para in paragraphs[:50]:
        para = para.strip()
        if not para:
            continue
        blocks.append(build_text_block(para))

    if not blocks:
        return

    await _append_block_chunk(doc_token, [RichBlockSpec(block=block) for block in blocks], client, 0)


async def _append_rich_blocks(
    document_id: str,
    block_specs: Sequence[RichBlockSpec],
    client: lark.Client,
) -> None:
    specs = list(block_specs)
    if not specs:
        return

    insert_index = 0
    for chunk in _chunked(specs, MAX_BLOCKS_PER_REQUEST):
        response_blocks = await _append_block_chunk(document_id, chunk, client, insert_index)
        insert_index += len(chunk)
        await _append_callout_children(document_id, chunk, response_blocks, client)


async def _append_block_chunk(
    document_id: str,
    block_specs: Sequence[RichBlockSpec],
    client: lark.Client,
    index: int,
) -> list[Block]:
    req_body = (
        CreateDocumentBlockChildrenRequestBody.builder()
        .children([spec.block for spec in block_specs])
        .index(index)
        .build()
    )
    req = (
        CreateDocumentBlockChildrenRequest.builder()
        .document_id(document_id)
        .block_id(document_id)
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.to_thread(client.docx.v1.document_block_children.create, req)
    if not resp.success():
        raise RuntimeError(f"追加文档内容失败: {resp.msg} (code={resp.code})")
    return list((resp.data.children or []) if resp.data else [])


async def _append_callout_children(
    document_id: str,
    block_specs: Sequence[RichBlockSpec],
    created_blocks: Sequence[Block],
    client: lark.Client,
) -> None:
    if len(created_blocks) != len(block_specs):
        logger.warning(
            "文档块创建返回数量与请求不一致: expected=%s actual=%s",
            len(block_specs),
            len(created_blocks),
        )

    for spec, created_block in zip(block_specs, created_blocks):
        if not spec.child_blocks:
            continue
        if not created_block.block_id:
            logger.warning("callout 块缺少 block_id，跳过子块追加")
            continue
        await _append_child_blocks(document_id, created_block.block_id, spec.child_blocks, client)


async def _append_child_blocks(
    document_id: str,
    parent_block_id: str,
    child_blocks: Sequence[Block],
    client: lark.Client,
) -> None:
    insert_index = 0
    for chunk in _chunked(list(child_blocks), MAX_BLOCKS_PER_REQUEST):
        req_body = (
            CreateDocumentBlockChildrenRequestBody.builder()
            .children(chunk)
            .index(insert_index)
            .build()
        )
        req = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(document_id)
            .block_id(parent_block_id)
            .request_body(req_body)
            .build()
        )
        resp = await asyncio.to_thread(client.docx.v1.document_block_children.create, req)
        if not resp.success():
            raise RuntimeError(f"追加 callout 子块失败: {resp.msg} (code={resp.code})")
        insert_index += len(chunk)


def _build_agent_block_specs(agent_results: Sequence[AgentResult]) -> list[RichBlockSpec]:
    if not agent_results:
        return [
            RichBlockSpec(block=build_heading_block(2, "暂无分析结果")),
            RichBlockSpec(block=build_bullet_block("当前没有可发布的分析内容。")),
        ]

    block_specs: list[RichBlockSpec] = []
    for result in agent_results:
        block_specs.append(RichBlockSpec(block=build_divider_block()))
        block_specs.append(RichBlockSpec(block=build_heading_block(2, result.agent_name or "未命名模块")))

        if not result.sections:
            block_specs.append(RichBlockSpec(block=build_heading_block(3, "分析结果")))
            block_specs.append(RichBlockSpec(block=build_bullet_block("暂无章节内容。")))

        for section in result.sections:
            block_specs.append(RichBlockSpec(block=build_heading_block(3, section.title or "分析结果")))
            lines = _extract_lines(section.content, max_lines=6)
            if not lines:
                lines = ["暂无内容。"]
            for line in lines:
                block_specs.append(RichBlockSpec(block=build_bullet_block(line)))

        insight_blocks = [build_text_block(text) for text in _build_agent_insights(result)]
        if insight_blocks:
            block_specs.append(
                RichBlockSpec(
                    block=build_callout_block(),
                    child_blocks=insight_blocks,
                )
            )

    return block_specs


def _build_agent_insights(result: AgentResult) -> list[str]:
    action_items = [
        _clean_line(item)
        for item in result.action_items
        if _clean_line(item) and not _clean_line(item).startswith("[摘要]")
    ]
    if action_items:
        return [f"关键洞察：{item}" if index == 0 else item for index, item in enumerate(action_items[:5])]

    for section in result.sections:
        lines = _extract_lines(section.content, max_lines=3)
        if lines:
            return [f"关键洞察：{lines[0]}"] + lines[1:]

    return []


def _build_text_block(block_type: int, text: str) -> Block:
    attr = _BLOCK_ATTRS[block_type]
    block_text = _build_block_text(text)
    return Block.builder().block_type(block_type).__getattribute__(attr)(block_text).build()


def _build_block_text(text: str) -> Text:
    cleaned = text.strip()[:MAX_DOC_TEXT_LENGTH]
    text_run = TextRun.builder().content(cleaned).build()
    text_elem = TextElement.builder().text_run(text_run).build()
    return Text.builder().elements([text_elem]).build()


def _extract_lines(text: str, max_lines: int) -> list[str]:
    lines = [_clean_line(line) for line in text.splitlines()]
    cleaned = [line for line in lines if line]
    if cleaned:
        return cleaned[:max_lines]
    compact = _clean_line(text)
    return [compact[:MAX_DOC_TEXT_LENGTH]] if compact else []


def _clean_line(line: str) -> str:
    return _LIST_PREFIX_RE.sub("", line.strip())[:MAX_DOC_TEXT_LENGTH]


def _chunked(items: Sequence, size: int) -> Iterable[Sequence]:
    for index in range(0, len(items), size):
        yield items[index:index + size]
