"""多维表格记录 CRUD — 直接调用飞书 HTTP API"""
import logging
from typing import Optional

import httpx

from app.feishu.aily import get_feishu_open_base_url as _get_base_url
from app.feishu.aily import get_tenant_access_token as _get_token
from app.feishu.retry import with_retry

logger = logging.getLogger(__name__)


async def list_records(
    app_token: str,
    table_id: str,
    filter_expr: Optional[str] = None,
    page_size: int = 50,
    max_records: int = 500,
) -> list[dict]:
    """返回表中记录列表，自动翻页直到无更多数据或达到 max_records 上限。

    filter_expr 示例：'CurrentValue.[状态]="待选题"'
    """
    return await with_retry(_list_records_impl, app_token, table_id, filter_expr, page_size, max_records)


async def _list_records_impl(
    app_token: str,
    table_id: str,
    filter_expr: Optional[str],
    page_size: int,
    max_records: int,
) -> list[dict]:
    base = _get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    all_items: list[dict] = []
    page_token: Optional[str] = None

    while True:
        token = await _get_token()
        params: dict = {"page_size": min(page_size, max_records - len(all_items))}
        if filter_expr:
            params["filter"] = filter_expr
        if page_token:
            params["page_token"] = page_token

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

        page_data = data.get("data", {})
        all_items.extend(page_data.get("items") or [])

        if not page_data.get("has_more") or len(all_items) >= max_records:
            break
        page_token = page_data.get("page_token")
        if not page_token:
            break

    return all_items[:max_records]


async def create_record(app_token: str, table_id: str, fields: dict) -> str:
    """新建单条记录，返回 record_id。"""
    return await with_retry(_create_record_impl, app_token, table_id, fields)


async def _create_record_impl(app_token: str, table_id: str, fields: dict) -> str:
    token = await _get_token()
    base = _get_base_url()
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
    await with_retry(_update_record_impl, app_token, table_id, record_id, fields)


async def _update_record_impl(
    app_token: str,
    table_id: str,
    record_id: str,
    fields: dict,
) -> None:
    token = await _get_token()
    base = _get_base_url()
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
