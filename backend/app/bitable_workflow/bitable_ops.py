"""Bitable record CRUD via Feishu HTTP API."""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.feishu.aily import get_feishu_open_base_url as _get_base_url
from app.feishu.aily import get_tenant_access_token as _get_token
from app.feishu.retry import with_retry

logger = logging.getLogger(__name__)
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30)
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


async def list_records(
    app_token: str,
    table_id: str,
    filter_expr: Optional[str] = None,
    page_size: int = 50,
    max_records: int = 500,
) -> list[dict]:
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
    if max_records <= 0:
        return []

    http = _get_http_client()
    while True:
        token = await _get_token()
        remaining = max_records - len(all_items)
        if remaining <= 0:
            break
        params: dict = {"page_size": min(page_size, remaining)}
        if filter_expr:
            params["filter"] = filter_expr
        if page_token:
            params["page_token"] = page_token

        resp = await http.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"list records failed: code={data.get('code')} msg={data.get('msg')}")

        page_data = data.get("data", {})
        all_items.extend(page_data.get("items") or [])

        if not page_data.get("has_more") or len(all_items) >= max_records:
            break
        page_token = page_data.get("page_token")
        if not page_token:
            break

    return all_items[:max_records]


async def create_record(app_token: str, table_id: str, fields: dict) -> str:
    return await with_retry(_create_record_impl, app_token, table_id, fields)


async def _create_record_impl(app_token: str, table_id: str, fields: dict) -> str:
    token = await _get_token()
    base = _get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    resp = await _get_http_client().post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"fields": fields},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"create record failed: code={data.get('code')} msg={data.get('msg')}")
    try:
        return data["data"]["record"]["record_id"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"create record response schema invalid: {data}") from exc


async def update_record(app_token: str, table_id: str, record_id: str, fields: dict) -> None:
    await with_retry(_update_record_impl, app_token, table_id, record_id, fields)


async def _update_record_impl(app_token: str, table_id: str, record_id: str, fields: dict) -> None:
    token = await _get_token()
    base = _get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    resp = await _get_http_client().put(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"fields": fields},
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"update record failed: code={data.get('code')} msg={data.get('msg')}")


async def delete_record(app_token: str, table_id: str, record_id: str) -> None:
    await with_retry(_delete_record_impl, app_token, table_id, record_id)


async def _delete_record_impl(app_token: str, table_id: str, record_id: str) -> None:
    token = await _get_token()
    base = _get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    resp = await _get_http_client().delete(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"delete record failed: code={data.get('code')} msg={data.get('msg')}")


async def delete_records_by_filter(
    app_token: str,
    table_id: str,
    filter_expr: str,
    max_records: int = 500,
) -> int:
    records = await list_records(app_token, table_id, filter_expr=filter_expr, max_records=max_records)
    deleted = 0
    delete_errors: list[str] = []
    for record in records:
        record_id = record.get("record_id")
        if not record_id:
            continue
        try:
            await delete_record(app_token, table_id, record_id)
            deleted += 1
        except Exception as exc:
            logger.error("Failed to delete record=%s: %s", record_id, exc)
            delete_errors.append(f"{record_id}: {exc}")
    if delete_errors:
        raise RuntimeError("partial record deletion failure: " + "; ".join(delete_errors[:3]))
    return deleted


def quote_filter_value(value: str) -> str:
    """Return a JSON string literal for Feishu formula filters."""
    return json.dumps(value or "", ensure_ascii=False)


def escape_filter_value(value: str) -> str:
    """Backward-compatible escaped content without surrounding quotes."""
    return quote_filter_value(value)[1:-1]
