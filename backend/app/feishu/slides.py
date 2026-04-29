"""Feishu Slides/Presentation creator with doc fallback."""
import html
import json
import logging
from typing import Optional, Sequence

import lark_oapi as lark

from app.agents.base_agent import AgentResult
from app.feishu import cli_bridge
from app.feishu.client import get_feishu_base_url
from app.feishu.doc import (
    RichBlockSpec,
    build_bullet_block,
    build_divider_block,
    build_heading_block,
    build_ordered_block,
    create_structured_document,
)
from app.core.redaction import redact_sensitive_text
from app.core.text_utils import truncate_with_marker

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
    if cli_bridge.is_cli_available():
        try:
            slides_xml = _build_cli_slides_xml(agent_results)
            cli_result = await cli_bridge.cli_create_slides(title, slides_xml, folder_token)
            slide_token = (
                cli_result.get("token")
                or cli_result.get("presentation_token")
                or cli_result.get("file_token")
                or cli_result.get("doc_token")
            )
            return {
                "presentation_token": slide_token,
                "url": cli_result.get("url") or _build_slide_url(slide_token),
                "title": title,
                "type": "slides",
            }
        except Exception as exc:
            logger.warning(
                "lark-cli slides creation failed: %s, trying REST API",
                redact_sensitive_text(exc, max_chars=500),
            )

    try:
        return await _create_via_presentation_api(title, agent_results, client, folder_token)
    except Exception as exc:
        logger.warning(
            "Presentation API failed: %s, falling back to doc",
            redact_sensitive_text(exc, max_chars=500),
        )
        return await _create_slides_as_doc(title, agent_results, client, folder_token)


async def _create_via_presentation_api(
    title: str,
    agent_results: list[AgentResult],
    client: lark.Client,
    folder_token: Optional[str] = None,
) -> dict:
    if not hasattr(client, "arequest"):
        raise AttributeError("lark client does not support raw async requests")

    body: dict = {"title": title}
    if folder_token:
        body["folder_token"] = folder_token

    create_req = (
        lark.BaseRequest.builder()
        .http_method(lark.HttpMethod.POST)
        .uri("/open-apis/presentation/v1/presentations")
        .token_types({lark.AccessTokenType.TENANT})
        .headers({"Content-Type": "application/json"})
        .body(body)
        .build()
    )
    response = await client.arequest(create_req)
    if not response.success():
        raise RuntimeError(
            f"Presentation v1 create failed: {redact_sensitive_text(response.msg, max_chars=500)} "
            f"(code={response.code})"
        )

    raw = json.loads(response.raw.content or b"{}")
    presentation_token = raw.get("data", {}).get("presentation", {}).get("token")
    if not presentation_token:
        raise RuntimeError("Presentation created but no token in response")

    if agent_results:
        await _populate_presentation(client, presentation_token, agent_results)

    url = f"{get_feishu_base_url()}/slides/{presentation_token}"
    return {
        "presentation_token": presentation_token,
        "url": url,
        "title": title,
        "type": "slides",
    }


async def _populate_presentation(
    client: lark.Client,
    presentation_token: str,
    agent_results: list[AgentResult],
) -> None:
    """Populate a new presentation with one slide per agent result."""
    slides_resp = await client.arequest(
        lark.BaseRequest.builder()
        .http_method(lark.HttpMethod.GET)
        .uri(f"/open-apis/presentation/v1/presentations/{presentation_token}/slides")
        .token_types({lark.AccessTokenType.TENANT})
        .build()
    )
    if not slides_resp.success():
        raise RuntimeError(
            f"Could not list slides: {redact_sensitive_text(slides_resp.msg, max_chars=500)}"
        )

    slides_data = json.loads(slides_resp.raw.content or b"{}")
    existing_ids: list[str] = slides_data.get("data", {}).get("slide_ids", [])

    for idx, result in enumerate(agent_results):
        if idx < len(existing_ids):
            slide_id = existing_ids[idx]
        else:
            new_slide_resp = await client.arequest(
                lark.BaseRequest.builder()
                .http_method(lark.HttpMethod.POST)
                .uri(
                    f"/open-apis/presentation/v1/presentations/{presentation_token}/slides"
                )
                .token_types({lark.AccessTokenType.TENANT})
                .headers({"Content-Type": "application/json"})
                .body({"index": idx})
                .build()
            )
            if not new_slide_resp.success():
                logger.warning(
                    "Slide %d creation failed: %s",
                    idx,
                    redact_sensitive_text(new_slide_resp.msg, max_chars=500),
                )
                continue
            slide_data = json.loads(new_slide_resp.raw.content or b"{}")
            slide_id = slide_data.get("data", {}).get("slide", {}).get("slide_id", "")
            if not slide_id:
                continue

        bullets = _build_slide_bullets(result)
        body_text = "\n".join(f"• {b}" for b in bullets) if bullets else "暂无可展示内容"
        agent_name = result.agent_name or "分析结果"

        add_resp = await client.arequest(
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.POST)
            .uri(
                f"/open-apis/presentation/v1/presentations/{presentation_token}"
                f"/slides/{slide_id}/elements"
            )
            .token_types({lark.AccessTokenType.TENANT})
            .headers({"Content-Type": "application/json"})
            .body({
                "requestType": "insert_after",
                "elements": [
                    {
                        "element_type": "shape",
                        "shape": {
                            "shape_type": "text_box",
                            "position": {"x": 36, "y": 36, "width": 648, "height": 72},
                            "text": {
                                "elements": [{"text_run": {"content": agent_name}}],
                            },
                        },
                    },
                    {
                        "element_type": "shape",
                        "shape": {
                            "shape_type": "text_box",
                            "position": {"x": 36, "y": 130, "width": 648, "height": 360},
                            "text": {
                                "elements": [{"text_run": {"content": truncate_with_marker(body_text, 800)}}],
                            },
                        },
                    },
                ],
            })
            .build()
        )
        if not add_resp.success():
            logger.warning(
                "Elements not added to slide %s (%s): %s",
                slide_id, agent_name, redact_sensitive_text(add_resp.msg, max_chars=500),
            )


async def _create_slides_as_doc(
    title: str,
    agent_results: list[AgentResult],
    client: lark.Client,
    folder_token: Optional[str] = None,
) -> dict:
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
                bullets.append(truncate_with_marker(clean_item, 180))
            if len(bullets) >= 5:
                return bullets

    for section in result.sections:
        for line in section.content.splitlines():
            clean_line = line.strip().lstrip("-•*0123456789.、 ")
            if clean_line:
                bullets.append(truncate_with_marker(clean_line, 180))
            if len(bullets) >= 5:
                return bullets

    return bullets[:5]


def _build_cli_slides_xml(agent_results: Sequence[AgentResult]) -> list[str]:
    if not agent_results:
        return [_build_slide_xml("暂无内容", "当前没有可展示的分析结果。")]

    slides_xml = []
    for result in agent_results:
        title = result.agent_name or "未命名模块"
        bullets = _build_slide_bullets(result)
        key_content = "\n".join(bullets) or "暂无可展示内容。"
        slides_xml.append(_build_slide_xml(title, truncate_with_marker(key_content, 900)))
    return slides_xml


def _build_slide_xml(title: str, content: str) -> str:
    escaped_title = html.escape(title, quote=True)
    escaped_content = html.escape(content, quote=True)
    return (
        f'<slide><elements><title text="{escaped_title}"/>'
        f'<text text="{escaped_content}"/></elements></slide>'
    )


def _build_slide_url(slide_token: Optional[str]) -> str:
    if not slide_token:
        return ""
    return f"{get_feishu_base_url()}/slides/{slide_token}"


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
