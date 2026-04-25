"""
Publisher：将分析结果发布到飞书各类资产
入口函数：publish_results()
"""
import asyncio
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentResult
from app.feishu import bitable, doc, im, slides, task as feishu_task
from app.feishu.cardkit import send_card_to_chat
from app.feishu.client import get_feishu_client
from app.core.event_emitter import EventEmitter
from app.core.text_utils import truncate_with_marker
from app.models.database import PublishedAsset

logger = logging.getLogger(__name__)


def _build_full_report(
    task_description: str,
    task_type_label: str,
    agent_results: list[AgentResult],
) -> str:
    """将所有 Agent 结果组合成一份完整报告文本"""
    parts = [f"# {task_type_label}报告\n\n**任务**：{task_description}\n"]
    for result in agent_results:
        parts.append(f"\n---\n## {result.agent_name}分析\n")
        for section in result.sections:
            parts.append(f"\n### {section.title}\n{section.content}\n")
    return "\n".join(parts)


def _collect_action_items(agent_results: list[AgentResult]) -> list[str]:
    """收集所有 Agent 的行动项（去重）"""
    seen = set()
    items = []
    for result in agent_results:
        for item in result.action_items:
            clean = item.strip()
            if clean and clean not in seen:
                seen.add(clean)
                items.append(clean)
    return items


async def _commit_with_retry(db: AsyncSession, context: str) -> None:
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            await db.commit()
            return
        except Exception as exc:
            last_exc = exc
            await db.rollback()
            if attempt < 2:
                await asyncio.sleep(0.1 * (2 ** attempt))
    raise RuntimeError(f"{context}: {last_exc}") from last_exc


async def _create_asset_placeholder(
    db: AsyncSession,
    task_id: str,
    asset_type: str,
    title: str,
) -> PublishedAsset:
    asset = PublishedAsset(
        task_id=task_id,
        asset_type=asset_type,
        title=title,
        meta={"status": "pending"},
    )
    db.add(asset)
    await _commit_with_retry(db, f"DB提交失败({asset_type}:pending)")
    return asset


async def _mark_asset_published(
    db: AsyncSession,
    asset: PublishedAsset,
    *,
    feishu_url: str = "",
    feishu_id: str = "",
    meta: dict | None = None,
) -> None:
    asset.feishu_url = feishu_url
    asset.feishu_id = feishu_id
    asset.meta = {"status": "published", **(meta or {})}
    await _commit_with_retry(db, f"DB提交失败({asset.asset_type}:published)")


async def _mark_asset_failed(
    db: AsyncSession,
    asset: PublishedAsset | None,
    error: Exception,
) -> None:
    if asset is None:
        return
    asset.meta = {
        **(asset.meta or {}),
        "status": "failed",
        "error": truncate_with_marker(error, 500),
    }
    try:
        await _commit_with_retry(db, f"DB提交失败({asset.asset_type}:failed)")
    except Exception as exc:
        logger.error(
            "Failed to mark published asset as failed",
            extra={"asset_type": asset.asset_type, "asset_id": asset.id, "error": str(exc)},
        )


async def publish_results(
    task_id: str,
    task_description: str,
    task_type_label: str,
    agent_results: list[AgentResult],
    asset_types: list[str],
    db: AsyncSession,
    emitter: EventEmitter,
    doc_title: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> dict:
    """
    根据 asset_types 发布到飞书。
    返回已发布资产列表及失败原因。
    """
    published = []
    errors: dict[str, str] = {}
    succeeded: set[str] = set()

    full_report = _build_full_report(task_description, task_type_label, agent_results)
    action_items = _collect_action_items(agent_results)
    title = doc_title or f"{task_type_label}报告"

    # 飞书文档
    if "doc" in asset_types:
        await emitter.emit_feishu_writing("文档")
        asset: PublishedAsset | None = None
        try:
            asset = await _create_asset_placeholder(db, task_id, "doc", title)
            result = await asyncio.wait_for(
                doc.create_rich_document(title=title, agent_results=agent_results),
                timeout=60.0,
            )
            await _mark_asset_published(
                db,
                asset,
                feishu_url=result["url"],
                feishu_id=result["doc_token"],
            )
        except Exception as e:
            await _mark_asset_failed(db, asset, e)
            errors["doc"] = str(e)
            logger.error(
                f"飞书文档发布失败: {e}",
                extra={"task_id": task_id, "asset_type": "doc", "error": str(e)},
            )
        else:
            published.append({"type": "doc", "title": title, "url": result["url"]})
            succeeded.add("doc")
            logger.info(
                f"飞书文档发布成功: {result['url']}",
                extra={"task_id": task_id, "asset_type": "doc"},
            )

    # 多维表格
    if "bitable" in asset_types:
        await emitter.emit_feishu_writing("多维表格")
        asset: PublishedAsset | None = None
        try:
            bitable_title = f"{title} - 分析协作"
            asset = await _create_asset_placeholder(db, task_id, "bitable", bitable_title)
            bitable_result = await asyncio.wait_for(
                bitable.create_analysis_bitable(
                    name=bitable_title,
                    agent_results=agent_results,
                ),
                timeout=60.0,
            )
            await _mark_asset_published(
                db,
                asset,
                feishu_url=bitable_result["url"],
                feishu_id=bitable_result["app_token"],
            )
        except Exception as e:
            await _mark_asset_failed(db, asset, e)
            errors["bitable"] = str(e)
            logger.error(
                f"多维表格发布失败: {e}",
                extra={"task_id": task_id, "asset_type": "bitable", "error": str(e)},
            )
        else:
            published.append({"type": "bitable", "title": bitable_title, "url": bitable_result["url"]})
            succeeded.add("bitable")
            logger.info(
                f"多维表格发布成功: {bitable_result['url']}",
                extra={"task_id": task_id, "asset_type": "bitable"},
            )

    # 演示文稿
    if "slides" in asset_types:
        await emitter.emit_feishu_writing("演示文稿")
        asset: PublishedAsset | None = None
        try:
            slides_title = f"{title} - 演示文稿"
            asset = await _create_asset_placeholder(db, task_id, "slides", slides_title)
            slides_result = await asyncio.wait_for(
                slides.create_presentation(
                    title=slides_title,
                    agent_results=agent_results,
                    client=get_feishu_client(),
                ),
                timeout=60.0,
            )
            await _mark_asset_published(
                db,
                asset,
                feishu_url=slides_result["url"],
                feishu_id=slides_result.get("presentation_token") or slides_result.get("doc_token"),
                meta={"render_type": slides_result["type"]},
            )
        except Exception as e:
            await _mark_asset_failed(db, asset, e)
            errors["slides"] = str(e)
            logger.error(
                f"演示文稿发布失败: {e}",
                extra={"task_id": task_id, "asset_type": "slides", "error": str(e)},
            )
        else:
            published.append({"type": "slides", "title": slides_title, "url": slides_result["url"]})
            succeeded.add("slides")
            logger.info(
                f"演示文稿发布成功: {slides_result['url']}",
                extra={"task_id": task_id, "asset_type": "slides"},
            )

    # 互动卡片
    if "card" in asset_types:
        from app.feishu.user_token import get_user_open_id

        _target_chat_id = chat_id
        _target_open_id = None
        if not _target_chat_id:
            _target_open_id = get_user_open_id()
            if not _target_open_id:
                raise ValueError("发送互动卡片需要提供飞书群 ID（chat_id），或先完成飞书 OAuth 授权")
        await emitter.emit_feishu_writing("互动卡片")
        asset: PublishedAsset | None = None
        try:
            asset = await _create_asset_placeholder(db, task_id, "card", "互动卡片")
            if _target_chat_id:
                card_result = await asyncio.wait_for(
                    send_card_to_chat(
                        chat_id=_target_chat_id,
                        title=f"📊 {title}",
                        results=agent_results,
                    ),
                    timeout=60.0,
                )
            else:
                from app.feishu.cardkit import send_card_to_user

                card_result = await asyncio.wait_for(
                    send_card_to_user(
                        open_id=_target_open_id,
                        title=f"📊 {title}",
                        results=agent_results,
                    ),
                    timeout=60.0,
                )
            await _mark_asset_published(
                db,
                asset,
                feishu_url=card_result.get("url") or "",
                feishu_id=card_result["message_id"],
            )
        except ValueError as e:
            await _mark_asset_failed(db, asset, e)
            raise
        except Exception as e:
            await _mark_asset_failed(db, asset, e)
            errors["card"] = str(e)
            logger.error(
                f"互动卡片发送失败: {e}",
                extra={"task_id": task_id, "asset_type": "card", "error": str(e)},
            )
        else:
            published.append({
                "type": "card",
                "title": "互动卡片已发送",
                "url": card_result.get("url") or "",
                "message_id": card_result["message_id"],
            })
            succeeded.add("card")
            logger.info(
                "互动卡片发送成功",
                extra={"task_id": task_id, "asset_type": "card"},
            )

    # 群消息
    if "message" in asset_types:
        from app.feishu.user_token import get_user_open_id

        _target_chat_id = chat_id
        _target_open_id = None
        if not _target_chat_id:
            _target_open_id = get_user_open_id()
            if not _target_open_id:
                raise ValueError("发送群消息需要提供飞书群 ID（chat_id），或先完成飞书 OAuth 授权")
        await emitter.emit_feishu_writing("消息")
        asset: PublishedAsset | None = None
        try:
            asset = await _create_asset_placeholder(db, task_id, "message", "群消息")
            # 找 CEO 助理的摘要
            summary_text = ""
            for r in agent_results:
                if r.agent_id == "ceo_assistant" and r.action_items:
                    for item in r.action_items:
                        if item.startswith("[摘要]"):
                            summary_text = item.replace("[摘要]", "").strip()
                            break
            if not summary_text:
                summary_text = f"【{task_type_label}】分析完成，共 {len(agent_results)} 个模块参与分析。"

            if _target_chat_id:
                msg_result = await asyncio.wait_for(
                    im.send_card_message(
                        title=f"📊 {title}",
                        content=summary_text,
                        chat_id=_target_chat_id,
                    ),
                    timeout=60.0,
                )
            else:
                msg_result = await asyncio.wait_for(
                    im.send_dm_card(
                        open_id=_target_open_id,
                        title=f"📊 {title}",
                        content=summary_text,
                    ),
                    timeout=60.0,
                )
            await _mark_asset_published(
                db,
                asset,
                feishu_id=msg_result["message_id"],
            )
        except ValueError as e:
            await _mark_asset_failed(db, asset, e)
            raise
        except Exception as e:
            await _mark_asset_failed(db, asset, e)
            errors["message"] = str(e)
            logger.error(
                f"群消息发送失败: {e}",
                extra={"task_id": task_id, "asset_type": "message", "error": str(e)},
            )
        else:
            published.append({"type": "message", "title": "群消息已发送",
                               "message_id": msg_result["message_id"]})
            succeeded.add("message")
            logger.info(
                "群消息发送成功",
                extra={"task_id": task_id, "asset_type": "message"},
            )

    # 飞书任务
    if "task" in asset_types:
        await emitter.emit_feishu_writing("任务")
        assets: list[PublishedAsset] = []
        try:
            # 过滤掉 [摘要] 开头的 action_items
            task_items = [i for i in action_items if not i.startswith("[摘要]")][:10]
            if not task_items:
                raise RuntimeError("没有可创建的行动项")
            for item in task_items:
                assets.append(
                    await _create_asset_placeholder(
                        db,
                        task_id,
                        "task",
                        truncate_with_marker(item, 200),
                    )
                )
            task_results = await asyncio.wait_for(
                feishu_task.batch_create_tasks(task_items),
                timeout=60.0,
            )
            if len(task_results) != len(assets):
                raise RuntimeError(f"飞书任务创建数量不一致: expected={len(assets)} actual={len(task_results)}")
            for asset, tr in zip(assets, task_results):
                asset.title = tr["title"]
                await _mark_asset_published(
                    db,
                    asset,
                    feishu_url=tr["url"],
                    feishu_id=tr["task_guid"],
                )
        except Exception as e:
            for asset in assets:
                await _mark_asset_failed(db, asset, e)
            errors["task"] = str(e)
            logger.error(
                f"飞书任务创建失败: {e}",
                extra={"task_id": task_id, "asset_type": "task", "error": str(e)},
            )
        else:
            published.append({"type": "task", "count": len(task_results),
                               "title": f"创建了 {len(task_results)} 个飞书任务"})
            succeeded.add("task")
            logger.info(
                f"飞书任务创建成功: {len(task_results)}",
                extra={"task_id": task_id, "asset_type": "task"},
            )

    if asset_types and not succeeded:
        raise HTTPException(
            status_code=500,
            detail={"message": "所有飞书发布均失败", "errors": errors},
        )

    return {"published": published, "errors": errors}
