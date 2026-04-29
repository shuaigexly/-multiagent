"""v8.6.19：列出 base 已有 Dashboard（仅 list 可读，飞书 OpenAPI 不开放创建/编辑）。

GET /open-apis/bitable/v1/apps/{app_token}/dashboards
- user_token 优先（让用户视角看到全部权限内 dashboard）
- 缺省 tenant_access_token（允许应用直接调）
- 完整分页 has_more / page_token
- 解析 data.dashboards[].block_id（飞书实际字段名，非 dashboard_id / items）
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.redaction import redact_sensitive_text
from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
from app.bitable_workflow.bitable_ops import _safe_json

logger = logging.getLogger(__name__)


async def list_dashboards(
    app_token: str,
    *,
    user_token: Optional[str] = None,
    page_size: int = 50,
) -> list[dict]:
    """返回 [{"block_id": "...", "name": "..."}, ...]"""
    base = get_feishu_open_base_url()
    token = user_token if user_token else await get_tenant_access_token()
    auth = {"Authorization": f"Bearer {token}"}
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/dashboards"

    items: list[dict] = []
    page_token: Optional[str] = None
    async with httpx.AsyncClient(timeout=20) as h:
        while True:
            params: dict = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            r = await h.get(url, headers=auth, params=params)
            body = _safe_json(r)
            if r.status_code != 200 or body.get("code") != 0:
                raise RuntimeError(
                    f"list dashboards failed: status={r.status_code} "
                    f"code={body.get('code')} msg={redact_sensitive_text(body.get('msg'), max_chars=500)}"
                )
            data = body.get("data") or {}
            for d in data.get("dashboards") or []:
                # 飞书返回的 ID 字段是 block_id，不是 dashboard_id
                items.append({
                    "block_id": d.get("block_id"),
                    "name": d.get("name"),
                })
            if not data.get("has_more"):
                break
            page_token = data.get("page_token") or data.get("next_page_token")
            if not page_token:
                break
    return items
