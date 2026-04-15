"""
ContextRetriever：检索用户关联的飞书资产作为任务上下文
MVP 阶段：从 feishu_context 字段读取用户手动提供的飞书资产列表
后续可扩展为：搜索飞书知识库、文档列表等
"""
from typing import Optional
from pydantic import BaseModel


class FeishuAsset(BaseModel):
    asset_type: str    # doc / bitable / wiki
    title: str
    url: str
    snippet: Optional[str] = None


class RetrievedContext(BaseModel):
    assets: list[FeishuAsset]
    summary: str


async def retrieve_context(
    task_description: str,
    feishu_context: Optional[dict] = None,
) -> RetrievedContext:
    """
    从飞书上下文中提取相关资产。
    MVP：直接使用用户传入的 feishu_context，不做自动搜索。
    """
    if not feishu_context:
        return RetrievedContext(assets=[], summary="未提供飞书上下文")

    assets = []
    raw_assets = feishu_context.get("assets", [])
    for a in raw_assets:
        try:
            assets.append(FeishuAsset(**a))
        except Exception:
            pass

    if assets:
        titles = "、".join(a.title for a in assets)
        summary = f"检索到 {len(assets)} 份关联飞书资产：{titles}"
    else:
        summary = "未找到关联飞书资产"

    return RetrievedContext(assets=assets, summary=summary)
