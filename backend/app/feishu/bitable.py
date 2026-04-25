"""飞书多维表格：创建 App、表、字段和记录"""
import asyncio
import logging
from typing import Optional, Sequence

import httpx

from lark_oapi.api.bitable.v1 import (
    AppTable,
    AppTableField,
    AppTableFieldProperty,
    AppTableFieldPropertyOption,
    AppTableRecord,
    BatchCreateAppTableRecordRequest,
    BatchCreateAppTableRecordRequestBody,
    CreateAppRequest,
    CreateAppTableFieldRequest,
    CreateAppTableRequest,
    CreateAppTableRequestBody,
    ReqApp,
    UpdateAppTableFieldRequest,
)

from app.agents.base_agent import AgentResult
from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
from app.feishu.client import get_feishu_base_url, get_feishu_client
from app.feishu.retry import with_retry
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)

TEXT_FIELD_TYPE = 1
SINGLE_SELECT_FIELD_TYPE = 3
LINKED_RECORD_FIELD_TYPE = 18
MAX_RECORDS_PER_REQUEST = 500
_http_client: httpx.AsyncClient | None = None
import threading as _threading
_http_client_lock = _threading.Lock()


def _get_http_client() -> httpx.AsyncClient:
    """v8.2 修复：懒初始化 race — 并发请求各自创建 client → 资源泄漏。"""
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


async def create_bitable(name: str) -> dict:
    return await with_retry(_create_bitable_impl, name)


async def create_table(app_token: str, table_name: str, fields: list[dict]) -> str:
    return await with_retry(_create_table_impl, app_token, table_name, fields)


async def create_view(
    app_token: str,
    table_id: str,
    view_name: str,
    view_type: str,
) -> str:
    """创建额外视图（看板/画册/甘特/表单/网格）。返回 view_id。

    view_type: "grid" | "kanban" | "gallery" | "gantt" | "form"
    首个看板视图会自动按第一个 SingleSelect 字段分组；画册视图按第一个附件/单选字段分组。
    """
    return await with_retry(_create_view_impl, app_token, table_id, view_name, view_type)


async def _create_view_impl(
    app_token: str,
    table_id: str,
    view_name: str,
    view_type: str,
) -> str:
    token = await get_tenant_access_token()
    base = get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views"
    r = await _get_http_client().post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"view_name": view_name, "view_type": view_type},
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"创建视图失败: {view_name} code={data.get('code')} msg={data.get('msg')}"
        )
    try:
        return data["data"]["view"]["view_id"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"创建视图响应结构异常: {data}") from exc


async def batch_add_records(app_token: str, table_id: str, records: list[dict]) -> int:
    return await with_retry(_batch_add_records_impl, app_token, table_id, records)


async def create_analysis_bitable(
    name: str,
    agent_results: list[AgentResult],
    client=None,
) -> dict:
    client = client or get_feishu_client()
    bitable_result = await with_retry(_create_bitable_impl, name, client=client)

    module_options = [result.agent_name for result in agent_results if result.agent_name] or ["暂无模块"]

    action_table_id = await _create_table_impl(
        app_token=bitable_result["app_token"],
        table_name="岗位分析行动项",
        fields=[
            {"field_name": "序号", "type": TEXT_FIELD_TYPE},
            {"field_name": "行动项", "type": TEXT_FIELD_TYPE},
            {"field_name": "来源模块", "type": SINGLE_SELECT_FIELD_TYPE, "options": module_options},
            {"field_name": "优先级", "type": SINGLE_SELECT_FIELD_TYPE, "options": ["高", "中", "低"]},
            {"field_name": "状态", "type": SINGLE_SELECT_FIELD_TYPE, "options": ["待处理", "进行中", "已完成"]},
        ],
        client=client,
    )

    summary_table_id = await _create_table_impl(
        app_token=bitable_result["app_token"],
        table_name="岗位分析摘要",
        fields=[
            {"field_name": "模块名称", "type": TEXT_FIELD_TYPE},
            {"field_name": "摘要", "type": TEXT_FIELD_TYPE},
            {"field_name": "关键发现", "type": TEXT_FIELD_TYPE},
        ],
        client=client,
    )

    action_records = _build_action_records(agent_results)
    if action_records:
        await with_retry(
            _batch_add_records_impl,
            app_token=bitable_result["app_token"],
            table_id=action_table_id,
            records=action_records,
            client=client,
        )

    summary_records = _build_summary_records(agent_results)
    if summary_records:
        await with_retry(
            _batch_add_records_impl,
            app_token=bitable_result["app_token"],
            table_id=summary_table_id,
            records=summary_records,
            client=client,
        )

    return {
        **bitable_result,
        "tables": {
            "actions": action_table_id,
            "summary": summary_table_id,
        },
    }


async def _create_bitable_impl(name: str, client=None) -> dict:
    """创建多维表格 App，返回 {"app_token": "...", "url": "..."}"""
    client = client or get_feishu_client()
    req_body = ReqApp.builder().name(name).build()
    req = CreateAppRequest.builder().request_body(req_body).build()
    resp = await asyncio.wait_for(
        asyncio.to_thread(client.bitable.v1.app.create, req),
        timeout=30.0,
    )
    if not resp.success():
        raise RuntimeError(f"创建多维表格失败: {resp.msg}")
    app_token = resp.data.app.app_token
    url = f"{get_feishu_base_url()}/base/{app_token}"
    logger.info("多维表格创建成功: %s", app_token)
    return {"app_token": app_token, "url": url, "name": name}


async def _create_table_impl(
    app_token: str,
    table_name: str,
    fields: list[dict],
    client=None,
) -> str:
    """在多维表格中创建表，返回 table_id"""
    client = client or get_feishu_client()
    req_body = CreateAppTableRequestBody.builder().table(AppTable.builder().name(table_name).build()).build()
    req = CreateAppTableRequest.builder().app_token(app_token).request_body(req_body).build()
    resp = await asyncio.wait_for(
        asyncio.to_thread(client.bitable.v1.app_table.create, req),
        timeout=30.0,
    )
    if not resp.success():
        raise RuntimeError(f"创建表格失败: {resp.msg}")
    if not resp.data:
        raise RuntimeError(f"创建表格成功但响应数据为空，无法获取 table_id")

    table_id = resp.data.table_id
    existing_field_ids = list(resp.data.field_id_list or [])
    await _ensure_table_fields(client, app_token, table_id, fields, existing_field_ids)
    return table_id


async def _ensure_table_fields(
    client,
    app_token: str,
    table_id: str,
    fields: Sequence[dict],
    existing_field_ids: Sequence[str],
) -> None:
    if not fields:
        return

    remaining_fields = list(fields)
    if existing_field_ids:
        await _rename_primary_field(
            client=client,
            app_token=app_token,
            table_id=table_id,
            field_id=existing_field_ids[0],
            field_name=remaining_fields[0]["field_name"],
        )
        remaining_fields = remaining_fields[1:]

    for field in remaining_fields:
        await _create_field(client, app_token, table_id, field)


async def _rename_primary_field(
    client,
    app_token: str,
    table_id: str,
    field_id: str,
    field_name: str,
) -> None:
    req_body = AppTableField.builder().field_name(field_name).build()
    req = (
        UpdateAppTableFieldRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .field_id(field_id)
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.wait_for(
        asyncio.to_thread(client.bitable.v1.app_table_field.update, req),
        timeout=30.0,
    )
    if not resp.success():
        raise RuntimeError(f"更新默认字段失败: {resp.msg}")


async def _create_field(
    client,
    app_token: str,
    table_id: str,
    field: dict,
) -> str:
    """通过 HTTP API 创建字段，支持全部 28 种类型 + ui_type + property。

    SDK builder 无法表达 rating/progress/currency/formula/datetime_created 等高级字段的
    property 配置，因此统一走 HTTP 路径，传入完整 payload。
    """
    return await _create_field_http(app_token, table_id, field)


async def _create_field_http(app_token: str, table_id: str, field: dict) -> str:
    """直接通过 Bitable Field POST 接口创建任意类型字段。

    field dict 支持：
      - field_name (必填)
      - type (必填, int) — 数据类型编号
      - ui_type (可选, str) — 如 "Rating"/"Progress"/"CreatedTime" 等，精确控制 UI 呈现
      - property (可选, dict) — 字段属性，如 {"rating": {"symbol": "star"}, "min": 0, "max": 5}
      - options (可选, list[str]) — SingleSelect/MultiSelect 的快捷字段，自动转成 property.options
      - table_id (可选, str) — 关联字段（type=18/21）的目标表 id
    """
    token = await get_tenant_access_token()
    base = get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"

    payload: dict = {"field_name": field["field_name"], "type": field["type"]}

    if "ui_type" in field:
        payload["ui_type"] = field["ui_type"]

    prop = dict(field.get("property") or {})

    # options 快捷方式 — 支持纯字符串或 {"name": ..., "color": N} 对象
    if field.get("options"):
        opts = []
        for item in field["options"]:
            if isinstance(item, str):
                opts.append({"name": item})
            elif isinstance(item, dict):
                opts.append(item)
        prop["options"] = opts

    # 关联字段（type=18/21）的 table_id 放入 property
    if field.get("table_id") and field["type"] in (18, 21):
        prop["table_id"] = field["table_id"]

    if prop:
        payload["property"] = prop

    r = await _get_http_client().post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"创建字段失败: {field['field_name']} code={data.get('code')} msg={data.get('msg')}"
        )
    try:
        return data["data"]["field"]["field_id"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"创建字段响应结构异常: {data}") from exc


async def _batch_add_records_impl(
    app_token: str,
    table_id: str,
    records: list[dict],
    client=None,
) -> int:
    """批量添加记录，返回成功条数"""
    client = client or get_feishu_client()
    success_count = 0

    for chunk in _chunked(records, MAX_RECORDS_PER_REQUEST):
        app_records = [AppTableRecord.builder().fields(record).build() for record in chunk]
        req_body = BatchCreateAppTableRecordRequestBody.builder().records(app_records).build()
        req = (
            BatchCreateAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .request_body(req_body)
            .build()
        )
        resp = await asyncio.wait_for(
            asyncio.to_thread(client.bitable.v1.app_table_record.batch_create, req),
            timeout=30.0,
        )
        if not resp.success():
            raise RuntimeError(f"批量添加记录失败: {resp.msg}")
        created_count = len(resp.data.records or []) if resp.data else 0
        if created_count != len(chunk):
            raise RuntimeError(
                f"批量添加记录数量不一致: expected={len(chunk)} actual={created_count}"
            )
        success_count += created_count

    return success_count


def _build_field(field: dict) -> AppTableField:
    builder = (
        AppTableField.builder()
        .field_name(field["field_name"])
        .type(field["type"])
    )
    property_value = _build_field_property(field)
    if property_value is not None:
        builder.property(property_value)
    return builder.build()


def _build_field_property(field: dict) -> Optional[AppTableFieldProperty]:
    options = field.get("options") or []
    if not options:
        return None

    option_values = [
        AppTableFieldPropertyOption.builder().name(option_name).build()
        for option_name in options
    ]
    return AppTableFieldProperty.builder().options(option_values).build()


def _build_action_records(agent_results: Sequence[AgentResult]) -> list[dict]:
    records = []
    seen = set()
    index = 1

    for result in agent_results:
        for item in result.action_items:
            clean_item = _clean_action_item(item)
            if not clean_item or clean_item.startswith("[摘要]"):
                continue
            dedupe_key = (result.agent_name, clean_item)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            records.append(
                {
                    "序号": str(index),
                    "行动项": clean_item,
                    "来源模块": result.agent_name or "暂无模块",
                    "优先级": "中",
                    "状态": "待处理",
                }
            )
            index += 1

    return records


def _build_summary_records(agent_results: Sequence[AgentResult]) -> list[dict]:
    records = []
    for result in agent_results:
        summary = "暂无摘要"
        if result.sections:
            summary = truncate_with_marker((result.sections[0].content or "").strip(), 300) or summary

        findings = _build_findings(result)
        records.append(
            {
                "模块名称": result.agent_name or "未命名模块",
                "摘要": summary,
                "关键发现": truncate_with_marker("；".join(findings), 500) if findings else "暂无关键发现",
            }
        )
    return records


def _build_findings(result: AgentResult) -> list[str]:
    findings = [_clean_action_item(item) for item in result.action_items if _clean_action_item(item)]
    filtered = [item for item in findings if not item.startswith("[摘要]")]
    if filtered:
        return filtered[:3]

    text_lines = []
    for section in result.sections:
        for line in (section.content or "").splitlines():
            clean_line = line.strip().lstrip("-•*0123456789.、 ")
            if clean_line:
                text_lines.append(truncate_with_marker(clean_line, 120))
            if len(text_lines) >= 3:
                return text_lines
    return text_lines[:3]


def _clean_action_item(item: str) -> str:
    return item.strip()


def _chunked(items: Sequence[dict], size: int) -> Sequence[Sequence[dict]]:
    return [items[index:index + size] for index in range(0, len(items), size)]
