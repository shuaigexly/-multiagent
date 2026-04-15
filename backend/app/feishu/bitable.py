"""飞书多维表格：创建 App、添加记录"""
import asyncio
import logging
from typing import Optional

from lark_oapi.api.bitable.v1 import (
    CreateAppRequest,
    ReqApp,
    CreateAppTableRequest,
    CreateAppTableRequestBody,
    AppTable,
    AppTableField,
    AppTableRecord,
    BatchCreateAppTableRecordRequest,
    BatchCreateAppTableRecordRequestBody,
)

from app.feishu.client import get_feishu_base_url, get_feishu_client
from app.feishu.retry import with_retry

logger = logging.getLogger(__name__)


async def create_bitable(name: str) -> dict:
    return await with_retry(_create_bitable_impl, name)


async def _create_bitable_impl(name: str) -> dict:
    """创建多维表格 App，返回 {"app_token": "...", "url": "..."}"""
    client = get_feishu_client()
    req_body = ReqApp.builder().name(name).build()
    req = CreateAppRequest.builder().request_body(req_body).build()
    resp = await asyncio.to_thread(client.bitable.v1.app.create, req)
    if not resp.success():
        raise RuntimeError(f"创建多维表格失败: {resp.msg}")
    app_token = resp.data.app.app_token
    url = f"{get_feishu_base_url()}/base/{app_token}"
    logger.info(f"多维表格创建成功: {app_token}")
    return {"app_token": app_token, "url": url, "name": name}


async def create_table(app_token: str, table_name: str, fields: list[dict]) -> str:
    return await with_retry(_create_table_impl, app_token, table_name, fields)


async def _create_table_impl(app_token: str, table_name: str, fields: list[dict]) -> str:
    """在多维表格中创建表，返回 table_id"""
    client = get_feishu_client()
    table_fields = [
        AppTableField.builder().field_name(f["field_name"]).type(f["type"]).build()
        for f in fields
    ]
    req_body = (
        CreateAppTableRequestBody.builder()
        .table(
            AppTable.builder()
            .name(table_name)
            .default_view_name("默认视图")
            .fields(table_fields)
            .build()
        )
        .build()
    )
    req = CreateAppTableRequest.builder().app_token(app_token).request_body(req_body).build()
    resp = await asyncio.to_thread(client.bitable.v1.app_table.create, req)
    if not resp.success():
        raise RuntimeError(f"创建表格失败: {resp.msg}")
    return resp.data.table_id


async def batch_add_records(app_token: str, table_id: str, records: list[dict]) -> int:
    return await with_retry(_batch_add_records_impl, app_token, table_id, records)


async def _batch_add_records_impl(app_token: str, table_id: str, records: list[dict]) -> int:
    """批量添加记录，返回成功条数"""
    client = get_feishu_client()
    app_records = [
        AppTableRecord.builder().fields(r).build()
        for r in records[:500]   # API 单次上限 500
    ]
    req_body = BatchCreateAppTableRecordRequestBody.builder().records(app_records).build()
    req = (
        BatchCreateAppTableRecordRequest.builder()
        .app_token(app_token)
        .table_id(table_id)
        .request_body(req_body)
        .build()
    )
    resp = await asyncio.to_thread(client.bitable.v1.app_table_record.batch_create, req)
    if not resp.success():
        logger.warning(f"批量添加记录失败: {resp.msg}")
        return 0
    return len(resp.data.records or [])
