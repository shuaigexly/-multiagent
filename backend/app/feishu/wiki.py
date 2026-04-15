"""飞书知识库：创建/读取 Wiki 节点"""
import logging
from typing import Optional

from lark_oapi.api.wiki.v2 import (
    CreateSpaceNodeRequest,
    CreateSpaceNodeRequestBody,
    Node,
)

from app.feishu.client import get_feishu_client

logger = logging.getLogger(__name__)


async def create_wiki_node(
    space_id: str,
    title: str,
    parent_node_token: Optional[str] = None,
) -> dict:
    """在知识库中创建节点（文档），返回 {"node_token": "...", "url": "..."}"""
    client = get_feishu_client()

    node_builder = Node.builder().title(title).obj_type("doc")
    if parent_node_token:
        node_builder = node_builder.parent_node_token(parent_node_token)

    req_body = CreateSpaceNodeRequestBody.builder().node(node_builder.build()).build()
    req = (
        CreateSpaceNodeRequest.builder()
        .space_id(space_id)
        .request_body(req_body)
        .build()
    )
    resp = client.wiki.v2.space_node.create(req)
    if not resp.success():
        raise RuntimeError(f"创建知识库节点失败: {resp.msg}")

    node_token = resp.data.node.node_token
    url = f"https://open.feishu.cn/wiki/{node_token}"
    logger.info(f"知识库节点创建成功: {node_token}")
    return {"node_token": node_token, "url": url, "title": title}
