"""
Publisher：将分析结果发布到飞书各类资产
入口函数：publish_results()
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import AgentResult
from app.feishu import bitable, doc, im, slides, task as feishu_task
from app.feishu.cardkit import send_card_to_chat
from app.feishu.client import get_feishu_client
from app.core.event_emitter import EventEmitter
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
) -> list[dict]:
    """
    根据 asset_types 发布到飞书。
    返回已发布资产列表。
    """
    published = []

    full_report = _build_full_report(task_description, task_type_label, agent_results)
    action_items = _collect_action_items(agent_results)
    title = doc_title or f"{task_type_label}报告"

    # 飞书文档
    if "doc" in asset_types:
        await emitter.emit_feishu_writing("文档")
        try:
            result = await doc.create_rich_document(title=title, agent_results=agent_results)
            asset = PublishedAsset(
                task_id=task_id,
                asset_type="doc",
                title=title,
                feishu_url=result["url"],
                feishu_id=result["doc_token"],
            )
            db.add(asset)
            await db.commit()
            published.append({"type": "doc", "title": title, "url": result["url"]})
            logger.info(f"飞书文档发布成功: {result['url']}")
        except Exception as e:
            logger.error(f"飞书文档发布失败: {e}")

    # 多维表格
    if "bitable" in asset_types:
        await emitter.emit_feishu_writing("多维表格")
        try:
            bitable_title = f"{title} - 分析协作"
            bitable_result = await bitable.create_analysis_bitable(
                name=bitable_title,
                agent_results=agent_results,
            )
            asset = PublishedAsset(
                task_id=task_id,
                asset_type="bitable",
                title=bitable_title,
                feishu_url=bitable_result["url"],
                feishu_id=bitable_result["app_token"],
            )
            db.add(asset)
            await db.commit()
            published.append({"type": "bitable", "title": bitable_title, "url": bitable_result["url"]})
        except Exception as e:
            logger.error(f"多维表格发布失败: {e}")

    # 演示文稿
    if "slides" in asset_types:
        await emitter.emit_feishu_writing("演示文稿")
        try:
            slides_title = f"{title} - 演示文稿"
            slides_result = await slides.create_presentation(
                title=slides_title,
                agent_results=agent_results,
                client=get_feishu_client(),
            )
            asset = PublishedAsset(
                task_id=task_id,
                asset_type="slides",
                title=slides_title,
                feishu_url=slides_result["url"],
                feishu_id=slides_result.get("presentation_token") or slides_result.get("doc_token"),
                meta={"render_type": slides_result["type"]},
            )
            db.add(asset)
            await db.commit()
            published.append({"type": "slides", "title": slides_title, "url": slides_result["url"]})
        except Exception as e:
            logger.error(f"演示文稿发布失败: {e}")

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
        try:
            if _target_chat_id:
                card_result = await send_card_to_chat(
                    chat_id=_target_chat_id,
                    title=f"📊 {title}",
                    results=agent_results,
                )
            else:
                from app.feishu.cardkit import send_card_to_user

                card_result = await send_card_to_user(
                    open_id=_target_open_id,
                    title=f"📊 {title}",
                    results=agent_results,
                )
            asset = PublishedAsset(
                task_id=task_id,
                asset_type="card",
                title="互动卡片",
                feishu_url=card_result.get("url"),
                feishu_id=card_result["message_id"],
            )
            db.add(asset)
            await db.commit()
            published.append({
                "type": "card",
                "title": "互动卡片已发送",
                "url": card_result.get("url"),
                "message_id": card_result["message_id"],
            })
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"互动卡片发送失败: {e}")

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
        try:
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
                msg_result = await im.send_card_message(
                    title=f"📊 {title}",
                    content=summary_text,
                    chat_id=_target_chat_id,
                )
            else:
                msg_result = await im.send_dm_card(
                    open_id=_target_open_id,
                    title=f"📊 {title}",
                    content=summary_text,
                )
            asset = PublishedAsset(
                task_id=task_id,
                asset_type="message",
                title="群消息",
                feishu_id=msg_result["message_id"],
            )
            db.add(asset)
            await db.commit()
            published.append({"type": "message", "title": "群消息已发送",
                               "message_id": msg_result["message_id"]})
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"群消息发送失败: {e}")

    # 飞书任务
    if "task" in asset_types and action_items:
        await emitter.emit_feishu_writing("任务")
        try:
            # 过滤掉 [摘要] 开头的 action_items
            task_items = [i for i in action_items if not i.startswith("[摘要]")][:10]
            task_results = await feishu_task.batch_create_tasks(task_items)
            for tr in task_results:
                asset = PublishedAsset(
                    task_id=task_id,
                    asset_type="task",
                    title=tr["title"],
                    feishu_url=tr["url"],
                    feishu_id=tr["task_guid"],
                )
                db.add(asset)
            await db.commit()
            published.append({"type": "task", "count": len(task_results),
                               "title": f"创建了 {len(task_results)} 个飞书任务"})
        except Exception as e:
            logger.error(f"飞书任务创建失败: {e}")

    return published
