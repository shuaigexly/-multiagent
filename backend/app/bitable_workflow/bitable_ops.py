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
import threading as _threading
_http_client_lock = _threading.Lock()


def _get_http_client() -> httpx.AsyncClient:
    """v8.2 修复：懒初始化 race — 并发首次请求会各自创建 httpx client，
    后建的覆盖前者 → 前者永不被 close → 资源泄漏（FD + connection pool）。
    threading.Lock 双检保证只有一个实例。
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        with _http_client_lock:
            if _http_client is None or _http_client.is_closed:
                _http_client = httpx.AsyncClient(timeout=30)
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


# ===== v8.6.19 Phase 0 — capability detection 基础设施 =====

def _safe_json(resp: httpx.Response) -> dict:
    """v8.6.19：飞书 5xx / 网关偶发返回 HTML 或纯文本，r.json() 直接 raise 没上下文。
    统一返回 {"code": -1, "msg": "non-JSON response (status=...): ..."}，
    让上层 RuntimeError 带清晰 status，便于排错。
    """
    try:
        return resp.json()
    except Exception:
        return {
            "code": -1,
            "msg": f"non-JSON response (status={resp.status_code}): {resp.text[:200]!r}",
        }


# field_exists 进程内缓存：(app_token, table_id) -> (set[field_name], unix_ts)
_FIELD_CACHE: dict[tuple[str, str], tuple[set[str], float]] = {}
_FIELD_CACHE_TTL = 60.0  # 秒
_FIELD_CACHE_LOCK = _threading.Lock()


def _invalidate_field_cache(app_token: str, table_id: str) -> None:
    """字段创建/失败降级后主动失效，避免 cycle 内拿到旧 miss 值。"""
    with _FIELD_CACHE_LOCK:
        _FIELD_CACHE.pop((app_token, table_id), None)


async def _fetch_field_names(app_token: str, table_id: str) -> set[str]:
    """GET /apps/{token}/tables/{tid}/fields 拉所有字段名。"""
    import time as _time
    base = _get_base_url()
    token = await _get_token()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    r = await _get_http_client().get(url, headers={"Authorization": f"Bearer {token}"})
    body = _safe_json(r)
    if r.status_code != 200 or body.get("code") != 0:
        raise RuntimeError(
            f"list fields failed: status={r.status_code} code={body.get('code')} msg={body.get('msg')}"
        )
    items = (body.get("data") or {}).get("items") or []
    names = {f.get("field_name") for f in items if f.get("field_name")}
    with _FIELD_CACHE_LOCK:
        _FIELD_CACHE[(app_token, table_id)] = (names, _time.time())
    return names


async def field_exists(
    app_token: str, table_id: str, field_name: str, *, refresh: bool = False,
) -> bool:
    """v8.6.19：判断某字段是否存在于指定表（带 60s 进程内缓存）。

    refresh=True 强制重拉。给 scheduler 做 capability detection（如「综合评分」公式
    是否建出来 → 决定 search 是否能 server-side sort）。
    """
    import time as _time
    key = (app_token, table_id)
    if not refresh:
        with _FIELD_CACHE_LOCK:
            entry = _FIELD_CACHE.get(key)
        if entry is not None:
            names, ts = entry
            if _time.time() - ts < _FIELD_CACHE_TTL:
                return field_name in names
    try:
        names = await _fetch_field_names(app_token, table_id)
    except Exception as exc:
        logger.warning("field_exists fetch failed (%s.%s): %s", app_token, table_id, exc)
        return False
    return field_name in names


# v8.6.19：optional 字段缺失错误码
# 注意：1254043 是 RecordIdNotFound（不是字段缺失），不能触发 optional fallback
_FIELD_MISSING_CODES = {"1254044", "1254045", "1254046"}
_FIELD_MISSING_MSGS = ("FieldNameNotFound", "FieldIdNotFound", "field not found")


def _is_field_missing_error(exc: Exception) -> bool:
    """检测异常是否表明 fields 中包含目标表不存在的字段。"""
    text = str(exc)
    if any(code in text for code in _FIELD_MISSING_CODES):
        return True
    return any(marker in text for marker in _FIELD_MISSING_MSGS)


async def update_record_optional_fields(
    app_token: str,
    table_id: str,
    record_id: str,
    fields: dict,
    optional_keys: list[str],
) -> dict:
    """v8.6.19：先用完整 fields 调 update_record；如果失败原因是字段不存在
    （1254044/1254045/1254046 或 message 含 FieldNameNotFound 等），从 fields 中
    移除 optional_keys 后重试一次。

    1254043（RecordIdNotFound）不触发 fallback —— 那是记录问题不是字段问题。

    返回 {"ok": bool, "fallback": bool, "removed": [...]}。
    """
    try:
        await update_record(app_token, table_id, record_id, fields)
        return {"ok": True, "fallback": False, "removed": []}
    except Exception as exc:
        if not _is_field_missing_error(exc):
            raise
        if not optional_keys:
            raise
        reduced = {k: v for k, v in fields.items() if k not in optional_keys}
        if not reduced:
            raise
        logger.info(
            "update_record_optional_fields: stripping optional keys %s due to: %s",
            optional_keys, exc,
        )
        await update_record(app_token, table_id, record_id, reduced)
        return {"ok": True, "fallback": True, "removed": list(optional_keys)}


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


async def get_record(app_token: str, table_id: str, record_id: str) -> dict:
    return await with_retry(_get_record_impl, app_token, table_id, record_id)


async def _get_record_impl(app_token: str, table_id: str, record_id: str) -> dict:
    token = await _get_token()
    base = _get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    resp = await _get_http_client().get(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get record failed: code={data.get('code')} msg={data.get('msg')}")
    try:
        return data["data"]["record"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"get record response schema invalid: {data}") from exc


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


# ===== v8.6.19 Phase B — search_records + batch_update + batch_delete =====

_AUTOMATIC_FIELDS_INVALID_CODES = {"1254000", "1254001"}


async def search_records(
    app_token: str,
    table_id: str,
    *,
    filter_conditions: Optional[list[dict]] = None,
    sort: Optional[list[dict]] = None,
    field_names: Optional[list[str]] = None,
    page_size: int = 100,
    max_records: int = 500,
    automatic_fields: bool = False,
) -> list[dict]:
    """v8.6.19：POST /records/search 全量分页拉取。

    body：filter / sort / field_names / automatic_fields
    query：page_size / page_token

    automatic_fields retry 条件收窄：仅 1254000/1254001 或 message 含
    "automatic_fields" 时重试一次不带该字段；5xx 走 with_retry（不剥离参数）。
    缺字段 / InvalidSort 等抛 RuntimeError，由上层 fallback。
    """
    return await with_retry(
        _search_records_impl, app_token, table_id,
        filter_conditions, sort, field_names, page_size, max_records, automatic_fields,
    )


async def _search_records_impl(
    app_token: str,
    table_id: str,
    filter_conditions: Optional[list[dict]],
    sort: Optional[list[dict]],
    field_names: Optional[list[str]],
    page_size: int,
    max_records: int,
    automatic_fields: bool,
) -> list[dict]:
    base = _get_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    items: list[dict] = []
    page_token: Optional[str] = None
    http = _get_http_client()
    sent_automatic_fields = automatic_fields
    while True:
        token = await _get_token()
        if max_records - len(items) <= 0:
            break
        params: dict = {"page_size": min(page_size, max_records - len(items))}
        if page_token:
            params["page_token"] = page_token
        body: dict = {}
        if filter_conditions:
            body["filter"] = {"conjunction": "and", "conditions": filter_conditions}
        if sort:
            body["sort"] = sort
        if field_names:
            body["field_names"] = field_names
        if sent_automatic_fields:
            body["automatic_fields"] = True
        resp = await http.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            params=params,
            json=body,
        )
        # 5xx 抛错让外层 with_retry 重试
        if 500 <= resp.status_code < 600:
            resp.raise_for_status()
        data = _safe_json(resp)
        code = str(data.get("code", "0"))
        msg = str(data.get("msg", ""))
        if data.get("code") != 0:
            # automatic_fields 参数被拒（仅特定错误码或 message 命中时剥离重试）
            if (
                sent_automatic_fields
                and (code in _AUTOMATIC_FIELDS_INVALID_CODES or "automatic_fields" in msg.lower())
            ):
                logger.warning(
                    "search_records: stripping automatic_fields and retrying once (code=%s msg=%s)",
                    code, msg,
                )
                sent_automatic_fields = False
                continue
            raise RuntimeError(
                f"search_records failed: status={resp.status_code} code={code} msg={msg}"
            )
        page = data.get("data") or {}
        items.extend(page.get("items") or [])
        if not page.get("has_more"):
            break
        page_token = page.get("page_token") or page.get("next_page_token")
        if not page_token:
            break
    return items[:max_records]


async def batch_update_records(
    app_token: str,
    table_id: str,
    records: list[dict],
) -> int:
    """v8.6.19：POST /records/batch_update。
    records: [{"record_id": "rec...", "fields": {...}}, ...]，500 条/次切片。
    单片失败 fallback 逐条串行 update_record（严禁 gather，避免 1254291 写冲突）。
    部分失败抛 RuntimeError 含失败 record_id 列表。
    """
    return await with_retry(_batch_update_records_impl, app_token, table_id, records)


async def _batch_update_records_impl(app_token: str, table_id: str, records: list[dict]) -> int:
    success = 0
    failed_ids: list[str] = []
    for chunk_start in range(0, len(records), 500):
        chunk = records[chunk_start:chunk_start + 500]
        try:
            updated = await _try_batch_update_chunk(app_token, table_id, chunk)
            success += updated
        except Exception as exc:
            logger.warning(
                "batch_update chunk failed (size=%d), falling back to serial: %s",
                len(chunk), exc,
            )
            # fallback：逐条串行 update（飞书同表并发写会触发 1254291 写冲突）
            for record in chunk:
                rid = record.get("record_id")
                if not rid:
                    continue
                try:
                    await update_record(app_token, table_id, rid, record.get("fields") or {})
                    success += 1
                except Exception as inner:
                    logger.error("serial update failed rid=%s: %s", rid, inner)
                    failed_ids.append(rid)
    if failed_ids:
        raise RuntimeError(f"batch_update_records partial failure: {failed_ids[:5]} (total {len(failed_ids)})")
    return success


async def _try_batch_update_chunk(app_token: str, table_id: str, chunk: list[dict]) -> int:
    """单片调 POST /records/batch_update。整片失败抛错由 _impl 走 fallback。"""
    base = _get_base_url()
    token = await _get_token()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_update"
    resp = await _get_http_client().post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"records": chunk},
    )
    if 500 <= resp.status_code < 600:
        resp.raise_for_status()
    data = _safe_json(resp)
    if data.get("code") != 0:
        raise RuntimeError(
            f"batch_update chunk failed: status={resp.status_code} code={data.get('code')} msg={data.get('msg')}"
        )
    returned = (data.get("data") or {}).get("records") or []
    return len(returned) if returned else len(chunk)


async def batch_delete_records(
    app_token: str,
    table_id: str,
    record_ids: list[str],
) -> int:
    """v8.6.19：POST /records/batch_delete。500 条/次。
    单片失败 fallback 逐条串行 delete_record。
    """
    return await with_retry(_batch_delete_records_impl, app_token, table_id, record_ids)


async def _batch_delete_records_impl(app_token: str, table_id: str, record_ids: list[str]) -> int:
    success = 0
    failed_ids: list[str] = []
    for chunk_start in range(0, len(record_ids), 500):
        chunk = record_ids[chunk_start:chunk_start + 500]
        try:
            deleted = await _try_batch_delete_chunk(app_token, table_id, chunk)
            success += deleted
        except Exception as exc:
            logger.warning(
                "batch_delete chunk failed (size=%d), falling back to serial: %s",
                len(chunk), exc,
            )
            for rid in chunk:
                if not rid:
                    continue
                try:
                    await delete_record(app_token, table_id, rid)
                    success += 1
                except Exception as inner:
                    logger.error("serial delete failed rid=%s: %s", rid, inner)
                    failed_ids.append(rid)
    if failed_ids:
        raise RuntimeError(f"batch_delete_records partial failure: {failed_ids[:5]} (total {len(failed_ids)})")
    return success


async def _try_batch_delete_chunk(app_token: str, table_id: str, chunk: list[str]) -> int:
    base = _get_base_url()
    token = await _get_token()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_delete"
    resp = await _get_http_client().post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"records": chunk},
    )
    if 500 <= resp.status_code < 600:
        resp.raise_for_status()
    data = _safe_json(resp)
    if data.get("code") != 0:
        raise RuntimeError(
            f"batch_delete chunk failed: status={resp.status_code} code={data.get('code')} msg={data.get('msg')}"
        )
    return len(chunk)


# v8.6.19：feature flag 控制 search/batch 优先；失败自动 fallback list+逐条
import os as _os
_USE_BATCH_RECORDS = _os.getenv("WORKFLOW_USE_BATCH_RECORDS", "1") == "1"


async def delete_records_by_filter(
    app_token: str,
    table_id: str,
    filter_expr: str,
    max_records: int = 500,
) -> int:
    """v8.6.19：优先 search_records + batch_delete_records；失败回退老路径。

    filter_expr 是 list_records 公式形式（如 'CurrentValue.[状态]="待分析"'），
    新路径不直接复用，因此先按 filter_expr 取 record_ids，再 batch_delete。
    """
    if _USE_BATCH_RECORDS:
        try:
            records = await list_records(
                app_token, table_id, filter_expr=filter_expr, max_records=max_records,
            )
            ids = [r.get("record_id") for r in records if r.get("record_id")]
            if not ids:
                return 0
            return await batch_delete_records(app_token, table_id, ids)
        except Exception as exc:
            logger.warning(
                "delete_records_by_filter batch path failed, falling back: %s", exc,
            )
    # 兜底老路径：list + 逐条
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
