"""飞书知识库：创建/读取 Wiki 节点"""
import asyncio
import logging
from typing import Optional

from lark_oapi.api.wiki.v2 import (
    CreateSpaceNodeRequest,
    Node,
)

from app.feishu.client import get_feishu_base_url, get_feishu_client
from app.feishu.retry import with_retry
from app.core.redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


async def create_wiki_node(
    space_id: str,
    title: str,
    parent_node_token: Optional[str] = None,
) -> dict:
    return await with_retry(_create_wiki_node_impl, space_id, title, parent_node_token)


async def _create_wiki_node_impl(
    space_id: str,
    title: str,
    parent_node_token: Optional[str] = None,
) -> dict:
    """在知识库中创建节点（文档），返回 {"node_token": "...", "url": "..."}"""
    client = get_feishu_client()

    node_builder = Node.builder().title(title).obj_type("doc")
    if parent_node_token:
        node_builder = node_builder.parent_node_token(parent_node_token)

    req = (
        CreateSpaceNodeRequest.builder()
        .space_id(space_id)
        .request_body(node_builder.build())
        .build()
    )
    resp = await asyncio.wait_for(
        asyncio.to_thread(client.wiki.v2.space_node.create, req),
        timeout=30.0,
    )
    if not resp.success():
        raise RuntimeError(f"创建知识库节点失败: {resp.msg}")

    node_token = resp.data.node.node_token
    url = f"{get_feishu_base_url()}/wiki/{node_token}"
    logger.info("知识库节点创建成功: %s", redact_sensitive_text(f"node_token={node_token}"))
    return {"node_token": node_token, "url": url, "title": title}
