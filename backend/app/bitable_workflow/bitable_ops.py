"""多维表格记录 CRUD — 直接调用飞书 HTTP API"""
import logging
from typing import Optional

import httpx

from app.feishu.aily import _get_feishu_open_base_url, _get_tenant_access_token

logger = logging.getLogger(__name__)


async def list_records(
    app_token: str,
    table_id: str,
    filter_expr: Optional[str] = None,
    page_size: int = 50,
) -> list[dict]:
    """返回表中记录列表，可用 filter_expr 按状态过滤。

    filter_expr 示例：'CurrentValue.[状态]="待选题"'
    """
    token = await _get_tenant_access_token()
    base = _get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    params: dict = {"page_size": page_size}
    if filter_expr:
        params["filter"] = filter_expr

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"列出记录失败: code={data.get('code')} msg={data.get('msg')}")
    return data.get("data", {}).get("items") or []


async def create_record(app_token: str, table_id: str, fields: dict) -> str:
    """新建单条记录，返回 record_id。"""
    token = await _get_tenant_access_token()
    base = _get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"fields": fields},
        )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"创建记录失败: code={data.get('code')} msg={data.get('msg')}")
    try:
        return data["data"]["record"]["record_id"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"创建记录响应结构异常: {data}") from exc


async def update_record(
    app_token: str,
    table_id: str,
    record_id: str,
    fields: dict,
) -> None:
    """更新已有记录的字段。"""
    token = await _get_tenant_access_token()
    base = _get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"

    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.put(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"fields": fields},
        )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"更新记录失败: code={data.get('code')} msg={data.get('msg')}")
