"""飞书多维表格：创建 App、表、字段和记录"""
import asyncio
import json
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
    """v8.6.6: 建完 base 立刻把"用户本人"加为 full_access 协作者 +
    （可选）打开链接分享。默认 app 建的 base 只有 app 有权限 → 用户/他人打开
    会得到「无权访问」。
    """
    result = await with_retry(_create_bitable_impl, name)
    try:
        await _grant_initial_permissions(result["app_token"])
    except Exception as exc:
        logger.warning("grant initial bitable permissions failed: %s", exc)
    return result


async def _grant_initial_permissions(app_token: str) -> None:
    """读取 .env 配置，把用户本人加为 full_access + 可选链接分享。

    所有失败都不阻塞建 base 主流程（warn 后继续）。
    需在飞书应用后台开启：
      - drive:drive  (协作者管理)
      - docs:permission.member:create
    """
    from app.core.settings import settings

    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()

    # 1. 把所有者本人加为 full_access — 三选一优先级：open_id > mobile > email
    owner_email = (settings.feishu_base_owner_email or "").strip()
    owner_mobile = (settings.feishu_base_owner_mobile or "").strip()
    owner_open_id = (settings.feishu_base_owner_open_id or "").strip()
    if not owner_open_id and owner_mobile:
        owner_open_id = await _resolve_contact_to_open_id(base, token, mobile=owner_mobile) or ""
        if not owner_open_id:
            logger.warning("owner mobile %r not found in Feishu tenant", owner_mobile)
    if not owner_open_id and owner_email:
        owner_open_id = await _resolve_contact_to_open_id(base, token, email=owner_email) or ""
        if not owner_open_id:
            logger.warning(
                "owner email %r not found in Feishu tenant — 用户必须是该飞书租户成员才能加协作者；"
                "请改填 FEISHU_BASE_OWNER_OPEN_ID 或 FEISHU_BASE_OWNER_MOBILE",
                owner_email,
            )
    if owner_open_id:
        try:
            await _add_bitable_member(
                base=base, token=token, app_token=app_token,
                member_type="openid", member_id=owner_open_id, perm="full_access",
            )
        except Exception as exc:
            logger.warning("add owner failed: %s", exc)

    # 2. 附加只读成员
    extras = [v.strip() for v in (settings.feishu_base_extra_viewers or "").split(",") if v.strip()]
    for v in extras:
        oid = v
        if "@" in v:
            oid = await _resolve_contact_to_open_id(base, token, email=v) or ""
        elif v.isdigit() and len(v) >= 7:
            oid = await _resolve_contact_to_open_id(base, token, mobile=v) or ""
        if "@" in v or (v.isdigit() and len(v) >= 7):
            if not oid:
                logger.warning("extra viewer %r not in tenant", v)
                continue
        try:
            await _add_bitable_member(
                base=base, token=token, app_token=app_token,
                member_type="openid", member_id=oid, perm="view",
            )
        except Exception as exc:
            logger.warning("add extra viewer %s failed: %s", v, exc)

    # 3. 打开「组织内任何人可查看」链接分享
    if settings.feishu_base_public_link_share:
        try:
            await _patch_public_link_share(base=base, token=token, app_token=app_token)
        except Exception as exc:
            logger.warning("public link share patch failed: %s", exc)


async def _resolve_contact_to_open_id(
    base: str, token: str,
    *, email: str | None = None, mobile: str | None = None,
) -> str | None:
    """飞书 contact API 把邮箱/手机反查成 open_id；不在租户内返回 None。

    POST /contact/v3/users/batch_get_id?user_id_type=open_id
      body: {"emails": ["..."]} 或 {"mobiles": ["..."]}
    """
    if not (email or mobile):
        return None
    body_payload: dict = {}
    if mobile:
        body_payload["mobiles"] = [mobile]
    if email:
        body_payload["emails"] = [email]
    url = f"{base}/open-apis/contact/v3/users/batch_get_id"
    r = await _get_http_client().post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"user_id_type": "open_id"},
        json=body_payload,
    )
    body: dict = {}
    try:
        body = r.json()
    except Exception:
        pass
    if r.status_code >= 400 or body.get("code", 0) != 0:
        logger.warning(
            "contact→open_id lookup failed: status=%s code=%s msg=%s",
            r.status_code, body.get("code"), body.get("msg"),
        )
        return None
    items = (body.get("data") or {}).get("user_list") or []
    for u in items:
        # 反查命中（只要有 user_id 就接受，不再严格 match email/mobile）
        if u.get("user_id"):
            return u["user_id"]
    return None


async def _add_bitable_member(
    *, base: str, token: str, app_token: str,
    member_type: str, member_id: str, perm: str,
) -> None:
    url = f"{base}/open-apis/drive/v1/permissions/{app_token}/members"
    payload = {
        "member_type": member_type,
        "member_id": member_id,
        "perm": perm,
        "type": "user",
    }
    r = await _get_http_client().post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"type": "bitable", "need_notification": "false"},
        json=payload,
    )
    body: dict = {}
    try:
        body = r.json()
    except Exception:
        pass
    if r.status_code >= 400 or body.get("code", 0) != 0:
        raise RuntimeError(
            f"add member failed status={r.status_code} code={body.get('code')} "
            f"msg={body.get('msg')} member={member_type}:{member_id} perm={perm}"
        )
    logger.info("Granted %s to %s:%s on bitable %s", perm, member_type, member_id, app_token)


async def _patch_public_link_share(*, base: str, token: str, app_token: str) -> None:
    """开启链接分享。链接级别由 settings.feishu_base_link_share_entity 控制：
      - tenant_readable: 组织内可查看（仅同租户成员）
      - anyone_readable: 任何人凭链接可查看（默认；解决"他人无法查看"最直接的方案）
      - tenant_editable / anyone_editable: 可编辑（飞书企业版可能受限）

    飞书接口 PATCH /drive/v1/permissions/{token}/public?type=bitable
    """
    from app.core.settings import settings
    entity = (settings.feishu_base_link_share_entity or "anyone_readable").strip()
    url = f"{base}/open-apis/drive/v1/permissions/{app_token}/public"
    payload = {"link_share_entity": entity}
    r = await _get_http_client().patch(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"type": "bitable"},
        json=payload,
    )
    body: dict = {}
    try:
        body = r.json()
    except Exception:
        pass
    if r.status_code >= 400 or body.get("code", 0) != 0:
        raise RuntimeError(
            f"public link share failed status={r.status_code} code={body.get('code')} msg={body.get('msg')}"
        )
    logger.info("Enabled tenant_readable link share on bitable %s", app_token)


async def create_table(app_token: str, table_name: str, fields: list[dict]) -> str:
    return await with_retry(_create_table_impl, app_token, table_name, fields)


async def create_view(
    app_token: str,
    table_id: str,
    view_name: str,
    view_type: str,
    *,
    filter_field: str | None = None,
    filter_operator: str = "is",
    filter_value: str | None = None,
) -> str:
    """创建额外视图（看板/画册/甘特/表单/网格）。返回 view_id。

    view_type: "grid" | "kanban" | "gallery" | "gantt" | "form"
    filter_field/filter_operator/filter_value: 可选的视图过滤条件，PATCH /views 后生效。
      仅 filter_info 在飞书 OpenAPI 公开支持；group_info/cover_field_id 不支持，需 UI 配置。

    v8.6.4 实证：飞书 POST /views 与 PATCH /views 都不接受 kanban group_info / gallery
    cover_field_id（hidden_fields 在 kanban/gallery 上也被拒，错误码 1254019）。
    GET /views 详情中也只暴露 filter_info / hidden_fields / hierarchy_config 三类
    property。kanban 默认分组、画册封面只能由用户首次打开视图后在 UI 中手动选定，
    或继承表的第一个 SingleSelect / Attachment 字段（飞书 UI 行为，非 API 保证）。
    """
    return await with_retry(
        _create_view_impl, app_token, table_id, view_name, view_type,
        filter_field, filter_operator, filter_value,
    )


async def _create_view_impl(
    app_token: str,
    table_id: str,
    view_name: str,
    view_type: str,
    filter_field: str | None = None,
    filter_operator: str = "is",
    filter_value: str | None = None,
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
        view_id = data["data"]["view"]["view_id"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"创建视图响应结构异常: {data}") from exc

    # 仅当传入过滤条件时才发 PATCH（filter_info 是飞书公开支持的 property key）
    if filter_field and filter_value is not None and view_id:
        await _patch_view_filter(
            app_token=app_token, table_id=table_id, view_id=view_id, view_type=view_type,
            filter_field=filter_field, filter_operator=filter_operator, filter_value=filter_value,
        )
    return view_id


async def _patch_view_filter(
    *, app_token: str, table_id: str, view_id: str, view_type: str,
    filter_field: str, filter_operator: str, filter_value: str,
) -> None:
    """通过 PATCH /views/{view_id} 设置 filter_info（飞书唯一公开支持的 property 配置）。

    kanban/gallery/grid 都接受 filter_info（实测）。

    SingleSelect 字段（type=3）value 必须是 JSON 编码的 option_id 数组：
      {"value": '["optXXX"]'}
    其它类型（text/number/date）value 是普通字符串。
    """
    token = await get_tenant_access_token()
    base = get_feishu_open_base_url()
    rf = await _get_http_client().get(
        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers={"Authorization": f"Bearer {token}"},
    )
    rf.raise_for_status()
    fields = rf.json().get("data", {}).get("items", []) or []
    field_obj = next((f for f in fields if f.get("field_name") == filter_field), None)
    if not field_obj:
        logger.warning("filter field %r not found in table %s", filter_field, table_id)
        return
    fid = field_obj.get("field_id")
    ftype = field_obj.get("type")

    # SingleSelect/MultiSelect: 把 value（选项名）转成 ["option_id"] 的 JSON 字符串
    encoded_value: str
    if ftype in (SINGLE_SELECT_FIELD_TYPE, 4):  # 3=SingleSelect 4=MultiSelect
        opts = (field_obj.get("property") or {}).get("options") or []
        opt_id = next((o.get("id") for o in opts if o.get("name") == filter_value), None)
        if not opt_id:
            logger.warning(
                "filter option %r not found in field %r (avail=%s)",
                filter_value, filter_field, [o.get("name") for o in opts],
            )
            return
        encoded_value = json.dumps([opt_id], ensure_ascii=True)
    else:
        encoded_value = str(filter_value)

    payload = {
        "property": {
            "filter_info": {
                "conjunction": "and",
                "conditions": [
                    {"field_id": fid, "operator": filter_operator, "value": encoded_value}
                ],
            }
        }
    }
    patch_url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/views/{view_id}"
    r = await _get_http_client().patch(
        patch_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:300]}
    if r.status_code >= 400 or body.get("code", 0) != 0:
        logger.warning(
            "view filter patch failed status=%s code=%s msg=%s body=%s view_type=%s payload=%s",
            r.status_code, body.get("code"), body.get("msg"),
            json.dumps(body, ensure_ascii=False)[:400], view_type,
            json.dumps(payload, ensure_ascii=False)[:400],
        )
    else:
        logger.info(
            "Set filter on view %s: %s %s %r",
            view_id, filter_field, filter_operator, filter_value,
        )


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
    """v8.6.3 重写：根本修复「多行文本」主字段问题。

    旧实现的 bug:
      - 用 SDK 返回的 existing_field_ids[0] 当主字段 ID rename
      - 但 SDK 在某些版本对此 PATCH 请求会"找不到字段就建一个"
      - 结果：原主字段「多行文本」纹丝不动，新建了重复的「任务标题」字段
      - 飞书画册/看板用主字段做卡片标题 → 全部显示"未命名记录"

    新实现:
      1. 建表后立即 HTTP GET fields，找 is_primary=True 的字段（飞书保证只有一个）
      2. 用 HTTP PATCH 直接改名（绕过 SDK 行为问题）
      3. schema[0] 不再走 _create_field，因为主字段已 rename 占用其名字
    """
    if not fields:
        return

    primary_id, primary_name, primary_type = await _find_primary_field(app_token, table_id)
    target_first = fields[0]
    target_first_name = target_first.get("field_name")

    if primary_id and primary_name != target_first_name:
        await _rename_field_via_http(
            app_token=app_token,
            table_id=table_id,
            field_id=primary_id,
            new_name=target_first_name,
            field_type=target_first.get("type", primary_type),
        )

    # schema[0] 已被 rename 到主字段；剩余字段逐个 create
    for field in fields[1:]:
        await _create_field(client, app_token, table_id, field)


async def _find_primary_field(app_token: str, table_id: str) -> tuple[str | None, str | None, int | None]:
    """GET fields 找 is_primary=True 的字段，返回 (field_id, field_name, type)。"""
    token = await get_tenant_access_token()
    base = get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    r = await _get_http_client().get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        return None, None, None
    items = data.get("data", {}).get("items", []) or []
    for f in items:
        if f.get("is_primary"):
            return f.get("field_id"), f.get("field_name"), f.get("type")
    return None, None, None


async def _rename_field_via_http(
    *, app_token: str, table_id: str, field_id: str, new_name: str, field_type: int = 1,
) -> None:
    """直接用 HTTP PATCH /fields/{field_id} 改名。

    同时传 type 字段（保持原 type）— 飞书要求 PATCH 必须带 type，否则报错。
    """
    if not new_name:
        return
    token = await get_tenant_access_token()
    base = get_feishu_open_base_url()
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}"
    payload = {"field_name": new_name, "type": int(field_type)}
    r = await _get_http_client().put(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(
            f"rename primary field failed: code={data.get('code')} msg={data.get('msg')} "
            f"field_id={field_id} new_name={new_name}"
        )
    logger.info("Renamed primary field %s → %r in table %s", field_id, new_name, table_id)


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
