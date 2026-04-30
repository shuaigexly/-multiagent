"""工作流管理 API — 初始化多维表格、启停调度循环、手动触发分析任务 + SSE 进度流"""
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sse_starlette.sse import EventSourceResponse

from app.bitable_workflow import bitable_ops, progress_broker, runner
from app.bitable_workflow.native_manifest import build_native_manifest
from app.bitable_workflow.native_installer import (
    _ALL_SURFACES as _NATIVE_ALL_SURFACES,
    _refresh_native_assets,
    apply_native_manifest,
    sync_native_asset_blueprints,
)
from app.bitable_workflow.scheduler import _base_route_transition_fields, _build_route_transition_fields, _derive_native_bitable_contract
from app.bitable_workflow.schema import ALL_STATUSES, ANALYSIS_DIMENSIONS, Status
from app.core.audit import record_audit
from app.core.auth import issue_stream_token, require_api_key, stream_audience_from_request, verify_stream_token
from app.core.env import get_int_env
from app.core.redaction import redact_sensitive_text

_VALID_DIMENSIONS: list[str] = ANALYSIS_DIMENSIONS
_VALID_STATUSES: set[str] = set(ALL_STATUSES)
_VALID_CONFIRM_ACTIONS: set[str] = {"approve", "execute", "retrospective"}
_VALID_SETUP_MODES: set[str] = {"seed_demo", "prod_empty", "template_only"}
_VALID_BASE_TYPES: set[str] = {"template", "production", "validation"}
MAX_WORKFLOW_SSE_SECONDS = get_int_env("MAX_WORKFLOW_SSE_SECONDS", 600, minimum=1)

router = APIRouter(
    prefix="/api/v1/workflow",
    tags=["workflow"],
)
logger = logging.getLogger(__name__)
_ARCHIVE_VERSION_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)

# 运行时状态（单进程内有效）
_state: dict = {}


def _strip_required_string(value: object) -> object:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise ValueError("不能为空")
        return normalized
    return value


def _strip_optional_string(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _normalize_path_id(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail=f"{label} 不能为空")
    return normalized


def _refresh_native_state_artifacts() -> None:
    app_token = str(_state.get("app_token") or "").strip()
    table_ids = _state.get("table_ids") or {}
    native_assets = _state.get("native_assets") or {}
    if not app_token or not table_ids or not native_assets:
        return
    sync_native_asset_blueprints(native_assets)
    _refresh_native_assets(native_assets)
    _state["native_assets"] = native_assets
    _state["native_manifest"] = build_native_manifest(
        app_token=app_token,
        base_url=str(_state.get("url") or ""),
        table_ids=table_ids,
        base_meta=_state.get("base_meta") or {},
        native_assets=native_assets,
    )


class SetupRequest(BaseModel):
    name: str = Field(default="内容运营虚拟组织", min_length=1, max_length=120)
    mode: str = "seed_demo"
    base_type: str = "validation"
    apply_native: bool = False

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        normalized = v.strip()
        if not normalized:
            raise ValueError("name 不能为空")
        return normalized

    @field_validator("mode")
    @classmethod
    def check_mode(cls, v: str) -> str:
        if v not in _VALID_SETUP_MODES:
            raise ValueError(f"mode 必须是以下之一: {sorted(_VALID_SETUP_MODES)}")
        return v

    @field_validator("base_type")
    @classmethod
    def check_base_type(cls, v: str) -> str:
        if v not in _VALID_BASE_TYPES:
            raise ValueError(f"base_type 必须是以下之一: {sorted(_VALID_BASE_TYPES)}")
        return v


class StartRequest(BaseModel):
    app_token: str = Field(min_length=1, max_length=64)
    table_ids: dict[str, str] = Field(..., min_length=3, max_length=32)
    interval: int = Field(default=30, ge=1, le=86400)
    analysis_every: int = Field(default=5, ge=1, le=1000)

    @field_validator("app_token", mode="before")
    @classmethod
    def strip_app_token(cls, v: object) -> object:
        return _strip_required_string(v)

    @model_validator(mode="after")
    def check_table_ids(self) -> "StartRequest":
        normalized_table_ids: dict[str, str] = {}
        for key, val in self.table_ids.items():
            normalized_key = key.strip() if isinstance(key, str) else key
            normalized_val = val.strip() if isinstance(val, str) else val
            if not isinstance(normalized_key, str) or not normalized_key or len(normalized_key) > 64:
                raise ValueError("table_ids key 必须是 1-64 字符字符串")
            if not isinstance(normalized_val, str) or not normalized_val:
                raise ValueError(f"table_ids['{key}'] 不能为空字符串")
            if len(normalized_val) > 128:
                raise ValueError(f"table_ids['{key}'] 超过长度限制")
            if normalized_key in normalized_table_ids:
                raise ValueError(f"table_ids 归一化后存在重复键: {normalized_key}")
            normalized_table_ids[normalized_key] = normalized_val
        self.table_ids = normalized_table_ids

        required = {"task", "report", "performance"}
        missing = required - self.table_ids.keys()
        if missing:
            raise ValueError(f"table_ids 缺少必需键: {missing}")
        if len(self.table_ids) > 32:
            raise ValueError("table_ids 数量超过限制")
        return self


class SeedRequest(BaseModel):
    # v8.6.20-r10（审计 #6）：每个 string 字段都有 max_length 防止 1MB payload 滚到
    # 飞书 API 触发非确定性 400/500，也防止 app_token/table_id 空串到下游 404。
    app_token: str = Field(min_length=1, max_length=64)
    table_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    dimension: str = Field(default="综合分析", max_length=50)
    background: str = Field(default="", max_length=10000)
    target_audience: str = Field(default="", max_length=500)
    output_purpose: str = Field(default="", max_length=500)
    task_source: str = Field(default="手工创建", max_length=50)
    business_owner: str = Field(default="", max_length=200)
    audience_level: str = Field(default="", max_length=100)
    success_criteria: str = Field(default="", max_length=2000)
    constraints: str = Field(default="", max_length=2000)
    business_stage: str = Field(default="", max_length=200)
    referenced_dataset: str = Field(default="", max_length=500)
    report_audience: str = Field(default="", max_length=200)
    report_audience_open_id: str = Field(default="", max_length=128)
    approval_owner: str = Field(default="", max_length=200)
    approval_owner_open_id: str = Field(default="", max_length=128)
    execution_owner: str = Field(default="", max_length=200)
    execution_owner_open_id: str = Field(default="", max_length=128)
    review_owner: str = Field(default="", max_length=200)
    review_owner_open_id: str = Field(default="", max_length=128)
    retrospective_owner: str = Field(default="", max_length=200)
    retrospective_owner_open_id: str = Field(default="", max_length=128)
    review_sla_hours: int = Field(default=0, ge=0, le=8760)
    template_name: str = Field(default="", max_length=200)
    template: str = Field(default="", max_length=200)

    @field_validator("app_token", "table_id", "title", mode="before")
    @classmethod
    def strip_required_strings(cls, v: object) -> object:
        return _strip_required_string(v)

    @field_validator(
        "dimension",
        "background",
        "target_audience",
        "output_purpose",
        "task_source",
        "business_owner",
        "audience_level",
        "success_criteria",
        "constraints",
        "business_stage",
        "referenced_dataset",
        "report_audience",
        "report_audience_open_id",
        "approval_owner",
        "approval_owner_open_id",
        "execution_owner",
        "execution_owner_open_id",
        "review_owner",
        "review_owner_open_id",
        "retrospective_owner",
        "retrospective_owner_open_id",
        "template_name",
        "template",
        mode="before",
    )
    @classmethod
    def strip_optional_strings(cls, v: object) -> object:
        return _strip_optional_string(v)

    @field_validator("dimension")
    @classmethod
    def check_dimension(cls, v: str) -> str:
        if v not in _VALID_DIMENSIONS:
            raise ValueError(f"dimension 必须是以下之一: {_VALID_DIMENSIONS}")
        return v

    @model_validator(mode="after")
    def normalize_template_name(self) -> "SeedRequest":
        if self.template and not self.template_name:
            self.template_name = self.template
        return self


class ConfirmRequest(BaseModel):
    app_token: str = Field(min_length=1, max_length=64)
    table_id: str = Field(min_length=1, max_length=64)
    record_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=32)
    actor: str = Field(default="", max_length=200)

    @field_validator("app_token", "table_id", "record_id", "action", mode="before")
    @classmethod
    def strip_required_strings(cls, v: object) -> object:
        return _strip_required_string(v)

    @field_validator("action")
    @classmethod
    def check_action(cls, v: str) -> str:
        if v not in _VALID_CONFIRM_ACTIONS:
            raise ValueError(f"action 必须是以下之一: {sorted(_VALID_CONFIRM_ACTIONS)}")
        return v

    @field_validator("actor", mode="before")
    @classmethod
    def strip_actor(cls, v: object) -> object:
        return _strip_optional_string(v)


class ApplyNativeRequest(BaseModel):
    surfaces: list[str] = Field(default_factory=list, max_length=len(_NATIVE_ALL_SURFACES))
    force: bool = False

    @field_validator("surfaces")
    @classmethod
    def check_surfaces(cls, values: list[str]) -> list[str]:
        valid = {"advperm", "form", "automation", "workflow", "dashboard", "role"}
        invalid = [value for value in values if value not in valid]
        if invalid:
            raise ValueError(f"surfaces 只能包含: {sorted(valid)}")
        return values


def _boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _confirm_action_allowed(action: str, task_fields: dict[str, object]) -> tuple[bool, str]:
    route = str(task_fields.get("工作流路由") or "").strip() or "未设置"
    if route in {"补数复核", "重新分析"}:
        return False, f"当前任务处于 {route} 异常分支，请先完成复核或重跑，不能执行 {action}"
    pending_approval = _boolish(task_fields.get("待拍板确认"))
    approved = _boolish(task_fields.get("是否已拍板"))
    pending_execution = _boolish(task_fields.get("待执行确认"))
    pending_retro = _boolish(task_fields.get("待复盘确认"))
    executed = _boolish(task_fields.get("是否已执行落地"))
    in_retro = _boolish(task_fields.get("是否进入复盘"))
    archived = str(task_fields.get("状态") or "").strip() == Status.ARCHIVED or str(task_fields.get("归档状态") or "").strip() == "已归档"

    if action == "approve":
        allowed = pending_approval or (route == "等待拍板" and not approved)
        expected = "等待拍板"
    elif action == "execute":
        allowed = pending_execution or (route == "直接执行" and not executed)
        expected = "直接执行"
    else:
        allowed = pending_retro or (executed and not in_retro and not archived)
        expected = "待复盘确认"
    if allowed:
        return True, ""
    return False, f"当前任务处于 {route}，不能执行 {action}；期望阶段为 {expected}"


def _route_transition_optional_keys() -> list[str]:
    return list(_base_route_transition_fields().keys())


def _build_approve_confirm_fields(
    *,
    actor: str,
    now_ms: int,
    task_fields: dict[str, object],
    route: str,
) -> tuple[dict[str, object], list[str], str, str, bool]:
    fields: dict[str, object] = _base_route_transition_fields()
    optional_keys = _route_transition_optional_keys() + ["拍板人", "拍板时间"]
    fields.update(
        {
            "是否已拍板": True,
            "拍板人": actor,
            "拍板时间": now_ms,
            # 拍板成功本身就消化了待发送汇报，否则视图会残留已拍板任务。
            "待发送汇报": False,
        }
    )
    action_name = "管理拍板确认"
    action_summary = f"{actor} 已回写拍板结果"
    promote_to_execution = route == "等待拍板" and _workflow_has_execution_items(task_fields)
    if promote_to_execution:
        fields.update(
            {
                "工作流路由": "直接执行",
                "归档状态": "待执行",
            }
        )
        fields.update(_build_route_transition_fields("直接执行", True, task_fields))
        optional_keys.extend(["工作流路由", "归档状态"])
        action_summary = f"{actor} 已回写拍板结果，并推进到执行队列"
    return fields, optional_keys, action_name, action_summary, promote_to_execution


def _build_execute_confirm_fields(now_ms: int) -> tuple[dict[str, object], list[str], str, str]:
    fields: dict[str, object] = _base_route_transition_fields()
    fields.update(
        {
            "是否已执行落地": True,
            "待复盘确认": True,
            "执行完成时间": now_ms,
            # 推进归档状态到待复盘，否则待复盘视图拉不到刚执行完的任务。
            "归档状态": "待复盘",
        }
    )
    optional_keys = _route_transition_optional_keys() + ["执行完成时间", "归档状态"]
    return fields, optional_keys, "执行落地确认", "已回写执行完成时间"


def _build_retrospective_confirm_fields() -> tuple[dict[str, object], list[str], str, str]:
    fields: dict[str, object] = _base_route_transition_fields()
    fields.update(
        {
            "是否进入复盘": True,
            "状态": Status.ARCHIVED,
            "归档状态": "已归档",
        }
    )
    optional_keys = _route_transition_optional_keys() + ["状态", "归档状态"]
    return fields, optional_keys, "进入复盘确认", "已完成复盘并归档"


def _build_archive_sync_payload(
    action: str,
    *,
    record_id: str,
    promote_to_execution: bool,
) -> tuple[dict[str, object], list[str]]:
    if action == "approve" and promote_to_execution:
        return (
            {
                "工作流路由": "直接执行",
                "归档状态": "待执行",
                "关联记录ID": record_id,
            },
            ["工作流路由", "归档状态", "关联记录ID"],
        )
    if action == "execute":
        return (
            {
                "归档状态": "待复盘",
                "关联记录ID": record_id,
            },
            ["归档状态", "关联记录ID"],
        )
    if action == "retrospective":
        return (
            {
                "归档状态": "已归档",
                "关联记录ID": record_id,
            },
            ["归档状态", "关联记录ID"],
        )
    return {}, []


def _normalize_task_record_fields(task_record: dict[str, object]) -> dict[str, object]:
    from app.bitable_workflow.scheduler import _flatten_record_fields

    raw_fields = task_record.get("fields") or {}
    task_fields = _flatten_record_fields(raw_fields)
    # SingleSelect 偶尔返回 dict {"text":"...","name":"..."}，再补一层
    for key, value in list(task_fields.items()):
        if isinstance(value, dict):
            task_fields[key] = value.get("text") or value.get("name") or ""
    return task_fields


async def _load_confirm_task_context(app_token: str, table_id: str, record_id: str) -> tuple[str, str, dict[str, object]]:
    task_record = await bitable_ops.get_record(app_token, table_id, record_id)
    task_fields = _normalize_task_record_fields(task_record)
    task_title = str(task_fields.get("任务标题") or "").strip()
    route = str(task_fields.get("工作流路由") or "").strip()
    return task_title, route, task_fields


def _build_action_log_fields(
    *,
    action_name: str,
    task_title: str,
    action_status: str,
    effective_route: str,
    action_summary: str,
    actor: str,
    action: str,
    record_id: str,
) -> dict[str, object]:
    return {
        "动作标题": f"{action_name} · {task_title}",
        "任务标题": task_title,
        "动作类型": "工作流记录",
        "动作状态": action_status,
        "工作流路由": effective_route,
        "动作内容": action_summary,
        "执行结果": f"{actor} 通过驾驶舱回写 {action}",
        "关联记录ID": record_id,
    }


def _build_automation_log_fields(
    *,
    action_name: str,
    task_title: str,
    action_status: str,
    effective_route: str,
    action_summary: str,
    actor: str,
    action: str,
    record_id: str,
) -> dict[str, object]:
    return {
        "日志标题": f"{action_name} · {task_title}",
        "任务标题": task_title,
        "节点名称": action_name,
        "触发来源": "驾驶舱回写",
        "执行状态": action_status,
        "工作流路由": effective_route,
        "日志摘要": action_summary,
        "详细结果": f"{actor} 于驾驶舱执行 {action}，已同步回写主表字段。",
        "关联记录ID": record_id,
    }


async def _write_confirm_log_records(
    *,
    app_token: str,
    action_tid: str | None,
    automation_log_tid: str | None,
    task_title: str,
    action_name: str,
    action_status: str,
    effective_route: str,
    action_summary: str,
    actor: str,
    action: str,
    record_id: str,
) -> None:
    if action_tid and task_title:
        await bitable_ops.create_record_optional_fields(
            app_token,
            action_tid,
            _build_action_log_fields(
                action_name=action_name,
                task_title=task_title,
                action_status=action_status,
                effective_route=effective_route,
                action_summary=action_summary,
                actor=actor,
                action=action,
                record_id=record_id,
            ),
            optional_keys=["工作流路由", "关联记录ID"],
        )
    if automation_log_tid and task_title:
        await bitable_ops.create_record_optional_fields(
            app_token,
            automation_log_tid,
            _build_automation_log_fields(
                action_name=action_name,
                task_title=task_title,
                action_status=action_status,
                effective_route=effective_route,
                action_summary=action_summary,
                actor=actor,
                action=action,
                record_id=record_id,
            ),
            optional_keys=["工作流路由", "触发来源", "详细结果", "关联记录ID"],
        )


async def _sync_confirm_archive_if_needed(
    *,
    action: str,
    app_token: str,
    archive_tid: str | None,
    record_id: str,
    task_title: str,
    promote_to_execution: bool,
) -> None:
    archive_sync_fields, archive_sync_optional_keys = _build_archive_sync_payload(
        action,
        record_id=record_id,
        promote_to_execution=promote_to_execution,
    )
    if archive_sync_fields:
        await _sync_delivery_archive(
            app_token,
            archive_tid,
            record_id,
            task_title,
            archive_sync_fields,
            archive_sync_optional_keys,
        )


def _workflow_has_execution_items(task_fields: dict[str, object]) -> bool:
    """是否有待落地执行项 — 优先看 scheduler 写入的「待创建执行任务」布尔，
    fallback 才扫文本（应对老 base 没有这字段的情况）。

    v8.6.20-r6 审计 #5/#9：之前只扫文本前缀会被模板/用户改坏；
    canonical 字段是 `待创建执行任务`。
    v8.6.20-r7 审计 #7：飞书 search/get_record 返回 text 字段为富文本数组
    `[{"text": "...", "type": "text"}]`，str() 直接拿到字面量永远不以「执行项：」
    开头 → fallback 永远 False → 已拍板任务卡在「等待拍板」无法 promote 到执行队列。
    必须先把富文本拍平。
    """
    def _flatten(v):
        if isinstance(v, list):
            return "".join(seg.get("text", "") for seg in v if isinstance(seg, dict))
        return v

    flag = _flatten(task_fields.get("待创建执行任务"))
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str):
        return flag.strip().lower() in {"true", "1", "是", "yes"}
    if isinstance(flag, (int, float)) and not isinstance(flag, bool):
        return bool(flag)
    # 老 base 没有该字段 → 文本兜底（先拍平富文本）
    payload_raw = _flatten(task_fields.get("工作流执行包"))
    payload = str(payload_raw or "").strip()
    if not payload:
        return False
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    saw_header = False
    for ln in lines:
        if ln.startswith(("执行项：", "执行项:")):
            saw_header = True
            continue
        if saw_header and ln.startswith(("- ", "• ", "* ")):
            return True
    return False


def _archive_version_rank(row: dict[str, object]) -> int:
    fields = (row.get("fields") if isinstance(row, dict) else None) or {}
    version = str(fields.get("汇报版本号") or "").strip()
    match = _ARCHIVE_VERSION_RE.match(version)
    if match:
        return int(match.group(1))
    return 0


async def _sync_delivery_archive(
    app_token: str,
    archive_tid: str | None,
    record_id: str,
    task_title: str,
    fields: dict[str, object],
    optional_keys: list[str],
) -> None:
    if not archive_tid:
        return
    archive_rows: list[dict[str, object]] = []
    try:
        if record_id:
            safe_record_id = bitable_ops.quote_filter_value(record_id)
            archive_rows = await bitable_ops.list_records(
                app_token,
                archive_tid,
                filter_expr=f"CurrentValue.[关联记录ID]={safe_record_id}",
                max_records=20,
            )
        if not archive_rows and task_title:
            safe_title = bitable_ops.quote_filter_value(task_title)
            archive_rows = await bitable_ops.list_records(
                app_token,
                archive_tid,
                filter_expr=f"CurrentValue.[任务标题]={safe_title}",
                max_records=20,
            )
    except Exception as exc:
        logger.warning("archive sync lookup failed record=%s title=%s: %s", record_id, task_title, exc)
        return
    if not archive_rows:
        return
    latest_row = max(archive_rows, key=_archive_version_rank)
    archive_fields = {key: value for key, value in fields.items() if key in {"工作流路由", "归档状态", "关联记录ID"}}
    if not archive_fields:
        return
    await bitable_ops.update_record_optional_fields(
        app_token,
        archive_tid,
        str(latest_row.get("record_id") or ""),
        archive_fields,
        optional_keys=[key for key in optional_keys if key in archive_fields],
    )


async def _resolve_seed_template_defaults(
    app_token: str,
    template_name: str,
    output_purpose: str,
) -> dict[str, object]:
    # v8.6.20-r8（审计 #7）：原子快照 _state 防 setup/seed 并发交错（Python dict 单 key
    # 读原子，但跨多 key 读会被中间的 setup 写交错，导致 app_token 来自 base A、
    # template_tid 来自 base B 这种不一致状态，下游查到 base A 的错表 / 404）。
    state_snapshot = dict(_state)
    state_app_token = str(state_snapshot.get("app_token") or "").strip()
    template_tid = (state_snapshot.get("table_ids") or {}).get("template")
    if not template_tid or (state_app_token and state_app_token != app_token):
        return {}

    try:
        templates = await bitable_ops.list_records(app_token, template_tid, max_records=200)
    except Exception as exc:
        logger.warning(
            "seed template lookup failed app=%s: %s",
            redact_sensitive_text(f"app_token={app_token}"),
            redact_sensitive_text(exc, max_chars=500),
        )
        return {}

    normalized_name = template_name.strip()
    normalized_purpose = output_purpose.strip()
    exact_match: dict | None = None
    purpose_match: dict | None = None
    fallback_match: dict | None = None
    # v8.6.20-r10（审计 #1）：拍平 Text 字段（飞书偶尔返富文本数组），否则模板名永
    # 远不命中，整个 seed-template 默认值流程静默失效。
    from app.bitable_workflow.scheduler import _flatten_record_fields
    for row in templates:
        fields = _flatten_record_fields(row.get("fields") or {})
        if not _boolish(fields.get("启用")):
            continue
        row_name = str(fields.get("模板名称") or "").strip()
        row_purpose = str(fields.get("适用输出目的") or "").strip()
        if normalized_name and row_name == normalized_name:
            exact_match = fields
            break
        if normalized_purpose and row_purpose == normalized_purpose and purpose_match is None:
            purpose_match = fields
        if not row_purpose and fallback_match is None:
            fallback_match = fields

    selected = exact_match or purpose_match or fallback_match
    if not selected:
        return {}
    return {
        "template_name": str(selected.get("模板名称") or "").strip(),
        "report_audience": str(selected.get("默认汇报对象") or "").strip(),
        "report_audience_open_id": str(selected.get("默认汇报对象OpenID") or "").strip(),
        "approval_owner": str(selected.get("默认拍板负责人") or "").strip(),
        "approval_owner_open_id": str(selected.get("默认拍板负责人OpenID") or "").strip(),
        "execution_owner": str(selected.get("默认执行负责人") or "").strip(),
        "execution_owner_open_id": str(selected.get("默认执行负责人OpenID") or "").strip(),
        "review_owner": str(selected.get("默认复核负责人") or "").strip(),
        "review_owner_open_id": str(selected.get("默认复核负责人OpenID") or "").strip(),
        "retrospective_owner": str(selected.get("默认复盘负责人") or "").strip(),
        "retrospective_owner_open_id": str(selected.get("默认复盘负责人OpenID") or "").strip(),
        "review_sla_hours": _safe_int(selected.get("默认复核SLA小时")),
    }


@router.post("/setup", dependencies=[Depends(require_api_key)])
async def workflow_setup(req: SetupRequest):
    """创建飞书多维表格结构（12 张业务表、精简工作流视图、模板中心）并写入初始分析任务。"""
    if runner.is_running():
        raise HTTPException(
            status_code=409,
            detail="Workflow loop is running; call /stop first before re-setup",
        )
    result = await runner.setup_workflow(req.name, mode=req.mode, base_type=req.base_type)
    if req.apply_native:
        try:
            native_apply = await apply_native_manifest(
                app_token=result["app_token"],
                base_url=result["url"],
                table_ids=result["table_ids"],
                base_meta=result["base_meta"],
                native_assets=result["native_assets"],
            )
            result["native_assets"] = native_apply["native_assets"]
            result["native_manifest"] = native_apply["native_manifest"]
            result["native_apply_report"] = native_apply["report"]
        except Exception as exc:
            logger.warning(
                "setup native apply failed app=%s: %s",
                redact_sensitive_text(f"app_token={result.get('app_token')}"),
                redact_sensitive_text(exc, max_chars=500),
            )
            result["native_apply_report"] = [
                {
                    "surface": "setup",
                    "name": "原生安装执行",
                    "status": "manual_finish_required",
                    "error": str(exc),
                }
            ]
    _state.clear()
    _state.update(result)
    await record_audit(
        "workflow.setup",
        target=result.get("app_token", ""),
        payload={"name": req.name, "url": result.get("url", ""), "mode": req.mode, "base_type": req.base_type, "apply_native": req.apply_native},
    )
    return result


@router.post("/start", dependencies=[Depends(require_api_key)])
async def workflow_start(req: StartRequest, background_tasks: BackgroundTasks):
    """启动七岗多智能体持续调度循环（后台运行）。"""
    if not runner.mark_starting():
        raise HTTPException(status_code=400, detail="Workflow already running")
    previous_app_token = str(_state.get("app_token") or "").strip()
    previous_task_table = str((_state.get("table_ids") or {}).get("task") or "").strip()
    if previous_app_token and (
        previous_app_token != req.app_token or previous_task_table != str(req.table_ids.get("task") or "").strip()
    ):
        for stale_key in ["url", "base_meta", "native_assets", "native_manifest", "native_apply_report"]:
            _state.pop(stale_key, None)
    _state.update({"app_token": req.app_token, "table_ids": req.table_ids})
    # v8.6.20-r14（审计 #2）：snapshot tenant/correlation 显式传给后台 loop —
    # 与 tasks.py / feishu_bot.py 同样模式，否则 cycle 期间 record_usage /
    # record_audit / cache 全部 fallback 到 tenant="default"。
    from app.core.observability import get_tenant_id as _get_tenant, get_correlation_id as _get_corr
    background_tasks.add_task(
        runner.run_workflow_loop,
        req.app_token,
        req.table_ids,
        req.interval,
        req.analysis_every,
        _get_tenant(),
        _get_corr(),
    )
    await record_audit(
        "workflow.start",
        target=req.app_token,
        payload={"interval": req.interval},
    )
    return {"status": "started", "interval": req.interval}


@router.post("/stop", dependencies=[Depends(require_api_key)])
async def workflow_stop():
    """停止调度循环。"""
    runner.stop_workflow()
    await record_audit("workflow.stop", target=_state.get("app_token", ""))
    return {"status": "stopped"}


@router.get("/status", dependencies=[Depends(require_api_key)])
async def workflow_status():
    """返回当前运行状态和多维表格信息。"""
    _refresh_native_state_artifacts()
    return {"running": runner.is_running(), "state": _state}


@router.get("/native-assets", dependencies=[Depends(require_api_key)])
async def workflow_native_assets():
    """返回当前 Base 的原生表单/自动化/工作流/仪表盘/角色蓝图。"""
    _refresh_native_state_artifacts()
    return {
        "app_token": _state.get("app_token", ""),
        "url": _state.get("url", ""),
        "base_meta": _state.get("base_meta") or {},
        "native_assets": _state.get("native_assets") or {},
    }


@router.get("/native-manifest", dependencies=[Depends(require_api_key)])
async def workflow_native_manifest():
    """返回当前 Base 的飞书原生安装包、命令模板和安装顺序。"""
    _refresh_native_state_artifacts()
    app_token = str(_state.get("app_token") or "").strip()
    return {
        "app_token": app_token,
        "url": _state.get("url", ""),
        "base_meta": _state.get("base_meta") or {},
        "native_manifest": _state.get("native_manifest") or {},
    }


@router.post("/native-manifest/apply", dependencies=[Depends(require_api_key)])
async def workflow_apply_native_manifest(req: ApplyNativeRequest):
    """执行飞书原生安装包，把 advperm/form/workflow/dashboard/role 等对象落到云侧。"""
    app_token = str(_state.get("app_token") or "").strip()
    table_ids = _state.get("table_ids") or {}
    base_meta = _state.get("base_meta") or {}
    native_assets = _state.get("native_assets") or {}
    if not app_token or not table_ids or not native_assets:
        raise HTTPException(status_code=409, detail="当前没有可执行原生化的 Base，请先完成 setup")
    result = await apply_native_manifest(
        app_token=app_token,
        base_url=str(_state.get("url") or ""),
        table_ids=table_ids,
        base_meta=base_meta,
        native_assets=native_assets,
        surfaces=req.surfaces,
        force=req.force,
    )
    _state["native_assets"] = result["native_assets"]
    _state["native_manifest"] = result["native_manifest"]
    _state["native_apply_report"] = result["report"]
    await record_audit(
        "workflow.native_manifest.apply",
        target=app_token,
        payload={
            "surfaces": req.surfaces or sorted(_NATIVE_ALL_SURFACES),
            "force": req.force,
        },
    )
    return result


@router.post("/seed", dependencies=[Depends(require_api_key)])
async def workflow_seed(req: SeedRequest):
    """向分析任务表写入一条新的待处理任务。"""
    fields = {
        "任务标题": req.title,
        "分析维度": req.dimension,
        "背景说明": req.background,
        "任务来源": req.task_source,
        "状态": Status.PENDING,
        "自动化执行状态": "未触发",
    }
    if req.output_purpose:
        fields["输出目的"] = req.output_purpose
    if req.target_audience:
        fields["目标对象"] = req.target_audience
    if req.business_owner:
        fields["业务归属"] = req.business_owner
    if req.audience_level:
        fields["汇报对象级别"] = req.audience_level
    if req.success_criteria:
        fields["成功标准"] = req.success_criteria
    if req.constraints:
        fields["约束条件"] = req.constraints
    if req.business_stage:
        fields["业务阶段"] = req.business_stage
    if req.referenced_dataset:
        fields["引用数据集"] = req.referenced_dataset

    template_defaults = await _resolve_seed_template_defaults(
        req.app_token,
        req.template_name,
        req.output_purpose,
    )
    resolved_template_name = str(template_defaults.get("template_name") or req.template_name or "").strip()
    if resolved_template_name:
        fields["套用模板"] = resolved_template_name
    if template_defaults.get("report_audience"):
        fields["汇报对象"] = str(template_defaults["report_audience"])
    if template_defaults.get("report_audience_open_id"):
        fields["汇报对象OpenID"] = str(template_defaults["report_audience_open_id"])
    if template_defaults.get("approval_owner"):
        fields["拍板负责人"] = str(template_defaults["approval_owner"])
    if template_defaults.get("approval_owner_open_id"):
        fields["拍板负责人OpenID"] = str(template_defaults["approval_owner_open_id"])
    if template_defaults.get("execution_owner"):
        fields["执行负责人"] = str(template_defaults["execution_owner"])
    if template_defaults.get("execution_owner_open_id"):
        fields["执行负责人OpenID"] = str(template_defaults["execution_owner_open_id"])
    if template_defaults.get("review_owner"):
        fields["复核负责人"] = str(template_defaults["review_owner"])
    if template_defaults.get("review_owner_open_id"):
        fields["复核负责人OpenID"] = str(template_defaults["review_owner_open_id"])
    if template_defaults.get("retrospective_owner"):
        fields["复盘负责人"] = str(template_defaults["retrospective_owner"])
    if template_defaults.get("retrospective_owner_open_id"):
        fields["复盘负责人OpenID"] = str(template_defaults["retrospective_owner_open_id"])
    if _safe_int(template_defaults.get("review_sla_hours")) > 0:
        fields["复核SLA小时"] = _safe_int(template_defaults["review_sla_hours"])

    if req.report_audience:
        fields["汇报对象"] = req.report_audience
    if req.report_audience_open_id:
        fields["汇报对象OpenID"] = req.report_audience_open_id
    if req.approval_owner:
        fields["拍板负责人"] = req.approval_owner
    if req.approval_owner_open_id:
        fields["拍板负责人OpenID"] = req.approval_owner_open_id
    if req.execution_owner:
        fields["执行负责人"] = req.execution_owner
    if req.execution_owner_open_id:
        fields["执行负责人OpenID"] = req.execution_owner_open_id
    if req.review_owner:
        fields["复核负责人"] = req.review_owner
    if req.review_owner_open_id:
        fields["复核负责人OpenID"] = req.review_owner_open_id
    if req.retrospective_owner:
        fields["复盘负责人"] = req.retrospective_owner
    if req.retrospective_owner_open_id:
        fields["复盘负责人OpenID"] = req.retrospective_owner_open_id
    if req.review_sla_hours > 0:
        fields["复核SLA小时"] = req.review_sla_hours

    # 新建任务在调度器接手前也应具备完整的原生责任/异常契约字段，
    # 避免未安装 A1 自动化或本地静态验收时出现空白责任面。
    fields.update(_derive_native_bitable_contract(fields))
    record_id = await bitable_ops.create_record_optional_fields(
        req.app_token,
        req.table_id,
        fields,
        optional_keys=[
            "目标对象",
            "任务来源",
            "业务归属",
            "汇报对象级别",
            "自动化执行状态",
            "输出目的",
            "成功标准",
            "约束条件",
            "业务阶段",
            "引用数据集",
            "套用模板",
            "汇报对象",
            "汇报对象OpenID",
            "拍板负责人",
            "拍板负责人OpenID",
            "执行负责人",
            "执行负责人OpenID",
            "复核负责人",
            "复核负责人OpenID",
            "复盘负责人",
            "复盘负责人OpenID",
            "复核SLA小时",
            "当前责任角色",
            "当前责任人",
            "当前原生动作",
            "异常状态",
            "异常类型",
            "异常说明",
        ],
    )
    await record_audit(
        "workflow.seed",
        target=record_id,
        payload={"title": req.title, "dimension": req.dimension, "app_token": req.app_token},
    )
    return {"record_id": record_id}


@router.post("/confirm", dependencies=[Depends(require_api_key)])
async def workflow_confirm(req: ConfirmRequest):
    """回写主表管理确认字段：拍板、执行落地、进入复盘。"""
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    actor = req.actor.strip() or "驾驶舱操作"
    try:
        # v8.6.20-r9（审计 #2）：飞书 get_record 把 Text/SingleSelect 字段返成富文本
        # 数组或 dict，必须先统一拍平，再做路由/状态判断。
        task_title, route, task_fields = await _load_confirm_task_context(req.app_token, req.table_id, req.record_id)
    except Exception as exc:
        logger.warning("confirm fetch task record failed record=%s: %s", req.record_id, exc)
        raise HTTPException(status_code=502, detail="获取任务上下文失败，无法执行确认，请稍后重试") from exc
    allowed, reason = _confirm_action_allowed(req.action, task_fields)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)
    fields: dict[str, object] = {}
    optional_keys: list[str] = []
    action_name = ""
    action_status = "已完成"
    action_summary = ""
    promote_to_execution = False

    if req.action == "approve":
        (
            approve_fields,
            approve_optional_keys,
            action_name,
            action_summary,
            promote_to_execution,
        ) = _build_approve_confirm_fields(
            actor=actor,
            now_ms=now_ms,
            task_fields=task_fields,
            route=route,
        )
        fields.update(approve_fields)
        optional_keys.extend(approve_optional_keys)
    elif req.action == "execute":
        execute_fields, execute_optional_keys, action_name, action_summary = _build_execute_confirm_fields(now_ms)
        fields.update(execute_fields)
        optional_keys.extend(execute_optional_keys)
    elif req.action == "retrospective":
        retro_fields, retro_optional_keys, action_name, action_summary = _build_retrospective_confirm_fields()
        fields.update(retro_fields)
        optional_keys.extend(retro_optional_keys)

    merged_task_fields = dict(task_fields)
    merged_task_fields.update(fields)
    fields.update(_derive_native_bitable_contract(merged_task_fields))
    optional_keys.extend(
        [
            "业务归属",
            "汇报对象级别",
            "拍板负责人",
            "复盘负责人",
            "当前责任角色",
            "当前责任人",
            "当前原生动作",
            "异常状态",
            "异常类型",
            "异常说明",
            "自动化执行状态",
        ]
    )

    await bitable_ops.update_record_optional_fields(
        req.app_token,
        req.table_id,
        req.record_id,
        fields,
        optional_keys=optional_keys,
    )
    await record_audit(
        "workflow.confirm",
        target=req.record_id,
        payload={"action": req.action, "actor": actor, "app_token": req.app_token},
    )

    table_ids = _state.get("table_ids") or {}
    action_tid = table_ids.get("action")
    automation_log_tid = table_ids.get("automation_log")
    archive_tid = table_ids.get("archive")
    effective_route = str(merged_task_fields.get("工作流路由") or route).strip()
    await _write_confirm_log_records(
        app_token=req.app_token,
        action_tid=action_tid,
        automation_log_tid=automation_log_tid,
        task_title=task_title,
        action_name=action_name,
        action_status=action_status,
        effective_route=effective_route,
        action_summary=action_summary,
        actor=actor,
        action=req.action,
        record_id=req.record_id,
    )
    await _sync_confirm_archive_if_needed(
        action=req.action,
        app_token=req.app_token,
        archive_tid=archive_tid,
        record_id=req.record_id,
        task_title=task_title,
        promote_to_execution=promote_to_execution,
    )
    return {"record_id": req.record_id, "action": req.action, "updated": fields}


@router.post("/stream-token/{task_record_id}", dependencies=[Depends(require_api_key)])
async def workflow_stream_token(
    task_record_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
):
    task_record_id = _normalize_path_id(task_record_id, "task_record_id")
    return {
        "token": issue_stream_token(
            subject=task_record_id,
            purpose="workflow-stream",
            ttl_seconds=60,
            audience=stream_audience_from_request(request),
        )
    }


async def _workflow_stream_generator(task_record_id: str, request: Request):
    start_time = time.monotonic()
    async for msg in progress_broker.subscribe(task_record_id):
        if await request.is_disconnected():
            break
        if time.monotonic() - start_time > MAX_WORKFLOW_SSE_SECONDS:
            break
        yield {"event": msg["event_type"], "data": json.dumps(msg, ensure_ascii=False)}


@router.get("/stream/{task_record_id}")
async def workflow_stream(
    task_record_id: Annotated[str, Path(min_length=1, max_length=128)],
    request: Request,
    token: Annotated[str, Query(max_length=4096)] = "",
):
    """SSE 流：实时推送 Bitable 工作流的 Wave 进度事件。

    订阅后立即接收 task.started / wave.completed / task.done / task.error 等事件。
    前端使用 EventSource 即可订阅；连接保持到 task.done/task.error 或客户端断开。
    """
    task_record_id = _normalize_path_id(task_record_id, "task_record_id")
    verify_stream_token(
        token,
        subject=task_record_id,
        purpose="workflow-stream",
        audience=stream_audience_from_request(request),
    )
    return EventSourceResponse(
        _workflow_stream_generator(task_record_id, request),
        media_type="text/event-stream",
    )


@router.get("/records", dependencies=[Depends(require_api_key)])
async def workflow_records(
    app_token: str = Query(..., min_length=1, max_length=64),
    table_id: str = Query(..., min_length=1, max_length=64),
    status: Optional[str] = Query(None, max_length=50),
):
    """查看多维表格中的记录（可按状态过滤）。"""
    app_token = app_token.strip()
    table_id = table_id.strip()
    status = status.strip() if status is not None else None
    if not app_token or not table_id:
        raise HTTPException(status_code=400, detail="app_token/table_id 不能为空")
    if status == "":
        status = None
    if status is not None and status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的状态值，有效值为: {sorted(_VALID_STATUSES)}",
        )
    filter_expr = f"CurrentValue.[状态]={bitable_ops.quote_filter_value(status)}" if status else None
    records = await bitable_ops.list_records(app_token, table_id, filter_expr=filter_expr)
    return {"count": len(records), "records": records}
