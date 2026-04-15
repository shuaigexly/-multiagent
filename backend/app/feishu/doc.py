"""飞书文档：创建文档，写入内容"""
import asyncio
import logging
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
    CreateDocumentResponse,
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    Block,
    Text,
    TextElement,
    TextRun,
)

from app.feishu.client import get_feishu_base_url, get_feishu_client
from app.feishu.retry import with_retry

logger = logging.getLogger(__name__)


async def create_document(title: str, content: str, folder_token: Optional[str] = None) -> dict:
    return await with_retry(_create_document_impl, title, content, folder_token)


async def _create_document_impl(title: str, content: str, folder_token: Optional[str] = None) -> dict:
    """
    创建飞书文档，写入标题和内容。
    返回 {"doc_token": "...", "url": "..."}
    """
    client = get_feishu_client()

    # 1. 创建文档
    req_body = CreateDocumentRequestBody.builder().title(title).build()
    req = CreateDocumentRequest.builder().request_body(req_body).build()

    resp: CreateDocumentResponse = await asyncio.to_thread(client.docx.v1.document.create, req)
    if not resp.success():
        raise RuntimeError(f"创建飞书文档失败: {resp.msg} (code={resp.code})")

    doc_token = resp.data.document.document_id
    logger.info(f"飞书文档创建成功: {doc_token}")

    # 2. 写入内容（分段落）
    await _append_text_blocks(client, doc_token, content)

    url = f"{get_feishu_base_url()}/docx/{doc_token}"
    return {"doc_token": doc_token, "url": url, "title": title}


async def _append_text_blocks(client: lark.Client, doc_token: str, content: str) -> None:
    """将内容按段落追加到文档"""
    paragraphs = content.split("\n\n")
    blocks = []
    for para in paragraphs[:50]:   # 限制段落数
        para = para.strip()
        if not para:
            continue
        # 简单文本块
        text_run = TextRun.builder().content(para[:2000]).build()
        text_elem = TextElement.builder().text_run(text_run).build()
        text_block = Text.builder().elements([text_elem]).build()
        block = Block.builder().block_type(2).text(text_block).build()  # 2 = text
        blocks.append(block)

    if not blocks:
        return

    req_body = (
        CreateDocumentBlockChildrenRequestBody.builder()
        .children(blocks)
        .index(0)
        .build()
    )
    req = (
        CreateDocumentBlockChildrenRequest.builder()
        .document_id(doc_token)
        .block_id(doc_token)   # 根块 ID = 文档 ID
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.to_thread(client.docx.v1.document_block_children.create, req)
    if not resp.success():
        logger.warning(f"追加文档内容失败: {resp.msg}")
