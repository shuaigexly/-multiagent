"""Feishu Slides/Presentation creator with doc fallback."""
import json
import logging
from typing import Optional, Sequence

import lark_oapi as lark

from app.agents.base_agent import AgentResult
from app.feishu.client import get_feishu_base_url
from app.feishu.doc import (
    RichBlockSpec,
    build_bullet_block,
    build_divider_block,
    build_heading_block,
    build_ordered_block,
    create_structured_document,
)

logger = logging.getLogger(__name__)


async def create_presentation(
    title: str,
    agent_results: list[AgentResult],
    client: lark.Client,
    folder_token: Optional[str] = None,
) -> dict:
    """
    Try Feishu Presentation API (raw HTTP), fall back to structured doc.
    Returns {"url": ..., "type": "slides"|"doc_slides"}
    """
    try:
        return await _create_via_presentation_api(title, agent_results, client, folder_token)
    except Exception as exc:
        logger.warning("Presentation API failed: %s, falling back to doc", exc)
        return await _create_slides_as_doc(title, agent_results, client, folder_token)


async def _create_via_presentation_api(
    title: str,
    agent_results: list[AgentResult],
    client: lark.Client,
    folder_token: Optional[str] = None,
) -> dict:
    del agent_results
    if not hasattr(client, "arequest"):
        raise AttributeError("lark client does not support raw async requests")

    body = {"title": title}
    if folder_token:
        body["folder_token"] = folder_token

    request_candidates = [
        lark.BaseRequest.builder()
        .http_method(lark.HttpMethod.POST)
        .uri("/open-apis/drive/v1/files")
        .token_types({lark.AccessTokenType.TENANT})
        .queries([("types", "slide")])
        .headers({"Content-Type": "application/json"})
        .body(body)
        .build(),
        lark.BaseRequest.builder()
        .http_method(lark.HttpMethod.POST)
        .uri("/open-apis/drive/v1/files/create")
        .token_types({lark.AccessTokenType.TENANT})
        .headers({"Content-Type": "application/json"})
        .body({**body, "type": "slide"})
        .build(),
    ]

    last_error: Exception | None = None
    for request in request_candidates:
        response = await client.arequest(request)
        if not response.success():
            last_error = RuntimeError(f"{request.uri} failed: {response.msg} (code={response.code})")
            continue

        raw_payload = json.loads(response.raw.content or b"{}")
        data = raw_payload.get("data") or {}
        file_token = (
            data.get("file_token")
            or data.get("token")
            or data.get("file_id")
            or data.get("document_id")
        )
        if not file_token:
            last_error = RuntimeError(f"{request.uri} succeeded but returned no slide token")
            continue

        url = data.get("url") or f"{get_feishu_base_url()}/slides/{file_token}"
        return {
            "presentation_token": file_token,
            "url": url,
            "title": title,
            "type": "slides",
        }

    if last_error is None:
        last_error = RuntimeError("no presentation API candidate could be attempted")
    raise last_error


async def _create_slides_as_doc(
    title: str,
    agent_results: list[AgentResult],
    client: lark.Client,
    folder_token: Optional[str] = None,
) -> dict:
    del client
    block_specs: list[RichBlockSpec] = [
        RichBlockSpec(block=build_heading_block(1, title)),
        RichBlockSpec(block=build_divider_block()),
    ]

    if not agent_results:
        block_specs.append(RichBlockSpec(block=build_heading_block(2, "暂无内容")))
        block_specs.append(RichBlockSpec(block=build_bullet_block("当前没有可展示的分析结果。")))
    else:
        for result in agent_results:
            block_specs.append(RichBlockSpec(block=build_heading_block(2, result.agent_name or "未命名模块")))
            bullets = _build_slide_bullets(result)
            for bullet in bullets or ["暂无可展示内容。"]:
                block_specs.append(RichBlockSpec(block=build_bullet_block(bullet)))
            block_specs.append(RichBlockSpec(block=build_divider_block()))

    block_specs.append(RichBlockSpec(block=build_heading_block(1, "总结")))
    summary_items = _collect_action_items(agent_results)
    if summary_items:
        for item in summary_items:
            block_specs.append(RichBlockSpec(block=build_ordered_block(item)))
    else:
        block_specs.append(RichBlockSpec(block=build_bullet_block("暂无行动项。")))

    doc_result = await create_structured_document(title=title, block_specs=block_specs, folder_token=folder_token)
    return {
        "doc_token": doc_result["doc_token"],
        "url": doc_result["url"],
        "title": title,
        "type": "doc_slides",
    }


def _build_slide_bullets(result: AgentResult) -> list[str]:
    bullets = []

    if result.action_items:
        for item in result.action_items:
            clean_item = item.strip()
            if clean_item and not clean_item.startswith("[摘要]"):
                bullets.append(clean_item[:180])
            if len(bullets) >= 5:
                return bullets

    for section in result.sections:
        for line in section.content.splitlines():
            clean_line = line.strip().lstrip("-•*0123456789.、 ")
            if clean_line:
                bullets.append(clean_line[:180])
            if len(bullets) >= 5:
                return bullets

    return bullets[:5]


def _collect_action_items(agent_results: Sequence[AgentResult]) -> list[str]:
    seen = set()
    items = []
    for result in agent_results:
        for item in result.action_items:
            clean_item = item.strip()
            if not clean_item or clean_item.startswith("[摘要]") or clean_item in seen:
                continue
            seen.add(clean_item)
            items.append(clean_item)
    return items
