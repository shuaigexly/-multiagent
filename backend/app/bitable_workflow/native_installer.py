"""Execute Feishu-native installation steps for the current Base."""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.native_manifest import build_native_manifest
from app.bitable_workflow.native_specs import (
    build_automation_specs,
    build_dashboard_specs,
    build_form_spec,
    build_role_specs,
    build_workflow_specs,
)
from app.core.text_utils import truncate_with_marker
from app.feishu.cli_bridge import cli_base, is_cli_available

logger = logging.getLogger(__name__)

_ALL_SURFACES = {"advperm", "form", "automation", "workflow", "dashboard", "role"}


async def apply_native_manifest(
    *,
    app_token: str,
    base_url: str,
    table_ids: dict[str, str],
    base_meta: dict[str, Any],
    native_assets: dict[str, Any],
    surfaces: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    targets = {item for item in (surfaces or []) if item in _ALL_SURFACES} or set(_ALL_SURFACES)
    assets = copy.deepcopy(native_assets or {})
    sync_native_asset_blueprints(assets)
    report: list[dict[str, Any]] = []

    if not is_cli_available():
        raise RuntimeError("lark-cli 不可用，无法执行飞书原生安装")

    applied_at = int(time.time())

    advperm_ready = True
    if "advperm" in targets or "role" in targets:
        advperm_ready = await _apply_advperm(app_token, assets, report)

    if "form" in targets:
        await _apply_form(app_token, table_ids, assets, report, force=force, applied_at=applied_at)
    if "automation" in targets:
        await _apply_automations(app_token, assets, report, force=force, applied_at=applied_at)
    if "workflow" in targets:
        await _apply_workflows(app_token, assets, report, force=force, applied_at=applied_at)
    if "dashboard" in targets:
        await _apply_dashboards(app_token, table_ids, assets, report, force=force, applied_at=applied_at)
    if "role" in targets:
        if advperm_ready:
            await _apply_roles(app_token, assets, report, force=force, applied_at=applied_at)
        else:
            _mark_roles_waiting_advperm(assets, report, applied_at=applied_at)

    await _write_native_install_logs(
        app_token=app_token,
        automation_log_tid=table_ids.get("automation_log"),
        report=report,
        base_meta=base_meta,
        applied_at=applied_at,
    )

    _refresh_native_assets(assets)
    manifest = build_native_manifest(
        app_token=app_token,
        base_url=base_url,
        table_ids=table_ids,
        base_meta=base_meta,
        native_assets=assets,
    )

    return {
        "applied_at": applied_at,
        "surfaces": sorted(targets),
        "report": report,
        "native_assets": assets,
        "native_manifest": manifest,
    }


def sync_native_asset_blueprints(assets: dict[str, Any]) -> dict[str, Any]:
    _sync_named_assets(assets, "automation_templates", build_automation_specs(), surface="automation")
    _sync_named_assets(assets, "workflow_blueprints", build_workflow_specs(), surface="workflow")
    _sync_named_assets(assets, "dashboard_blueprints", build_dashboard_specs(), surface="dashboard")
    _sync_named_assets(assets, "role_blueprints", build_role_specs(), surface="role")
    _sync_form_assets(assets)
    return assets


async def _apply_advperm(app_token: str, assets: dict[str, Any], report: list[dict[str, Any]]) -> bool:
    try:
        resp = await cli_base("+advperm-enable", "--base-token", app_token)
        data = _resp_data(resp)
        success = _resp_success(data)
        assets["advperm_state"] = "created" if success else "manual_finish_required"
        report.append(
            {
                "surface": "advperm",
                "name": "启用高级权限",
                "status": "created" if success else "manual_finish_required",
                "response": resp,
                "error": "" if success else "高级权限启用返回未确认 success=true",
            }
        )
        return success
    except Exception as exc:
        logger.warning("advperm enable failed: %s", exc)
        assets["advperm_state"] = _error_state(exc)
        report.append({"surface": "advperm", "name": "启用高级权限", "status": assets["advperm_state"], "error": str(exc)})
        return False


async def _apply_form(
    app_token: str,
    table_ids: dict[str, str],
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    force: bool,
    applied_at: int,
) -> None:
    forms = _asset_list(assets, "form_blueprints")
    if not forms:
        return
    form = forms[0]
    form_spec = build_form_spec()
    if not force and str(form.get("lifecycle_state") or "") == "created":
        report.append({"surface": "form", "name": str(form.get("name") or "任务收集表单"), "status": "skipped", "reason": "already_created"})
        return
    form_id = ""
    created_question_count = 0
    questions = list(form_spec.get("questions") or [])
    try:
        resp = await cli_base(
            "+form-create",
            "--base-token",
            app_token,
            "--table-id",
            table_ids["task"],
            "--name",
            str(form_spec["name"]),
            "--description",
            str(form_spec["description"]),
        )
        data = _resp_data(resp)
        form_id = str(data.get("id") or "")
        if not form_id:
            form["lifecycle_state"] = "manual_finish_required"
            form["cloud_object_id"] = ""
            form["applied_at"] = applied_at
            form["question_count"] = 0
            form["questions"] = questions
            form["description"] = str(form_spec["description"])
            form["next_step"] = "请先在飞书内确认表单是否已创建成功，再继续补题目和共享范围"
            form["blocking_reason"] = "表单创建返回中缺少 form_id"
            report.append(
                {
                    "surface": "form",
                    "name": str(form.get("name") or "任务收集表单"),
                    "status": "manual_finish_required",
                    "error": "表单创建返回中缺少 form_id",
                }
            )
            return
        if questions:
            for idx in range(0, len(questions), 10):
                batch = questions[idx : idx + 10]
                await cli_base(
                    "+form-questions-create",
                    "--base-token",
                    app_token,
                    "--table-id",
                    table_ids["task"],
                    "--form-id",
                    form_id,
                    "--questions",
                    _json(batch),
                )
                created_question_count += len(batch)
        form["lifecycle_state"] = "created"
        form["cloud_object_id"] = form_id
        form["applied_at"] = applied_at
        form["question_count"] = created_question_count
        form["questions"] = questions
        form["description"] = str(form_spec["description"])
        form["next_step"] = "继续在飞书 UI 中配置共享范围、提交成功页和后续跳转动作"
        form["blocking_reason"] = ""
        report.append(
            {
                "surface": "form",
                "name": str(form.get("name") or "任务收集表单"),
                "status": "created",
                "object_id": form["cloud_object_id"],
                "question_count": created_question_count,
            }
        )
    except Exception as exc:
        form["lifecycle_state"] = _error_state(exc)
        form["cloud_object_id"] = form_id
        form["applied_at"] = applied_at
        form["question_count"] = created_question_count
        form["questions"] = questions
        form["description"] = str(form_spec["description"])
        if form_id:
            form["next_step"] = "表单对象已经创建，但题目或后续配置未完整落下，请在飞书里补齐后重试"
        form["blocking_reason"] = str(exc)
        report.append(
            {
                "surface": "form",
                "name": str(form.get("name") or "任务收集表单"),
                "status": form["lifecycle_state"],
                "object_id": form_id,
                "question_count": created_question_count,
                "error": str(exc),
            }
        )


async def _apply_workflows(
    app_token: str,
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    force: bool,
    applied_at: int,
) -> None:
    specs = build_workflow_specs()
    for item, spec in zip(_asset_list(assets, "workflow_blueprints"), specs):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "workflow", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        try:
            resp = await cli_base("+workflow-create", "--base-token", app_token, "--json", _json(spec["body"]))
            data = _resp_data(resp)
            workflow_id = str(data.get("workflow_id") or "")
            enabled = False
            if workflow_id:
                enable_resp = await cli_base("+workflow-enable", "--base-token", app_token, "--workflow-id", workflow_id)
                enabled = _workflow_enabled(_resp_data(enable_resp), workflow_id)
            item["lifecycle_state"] = "created" if workflow_id and enabled else "manual_finish_required"
            item["cloud_object_id"] = workflow_id
            item["applied_at"] = applied_at
            item["next_step"] = "如需更强业务逻辑，可继续在飞书工作流里补成员映射、审批链和任务卡片动作"
            if not workflow_id:
                item["blocking_reason"] = "工作流创建返回中缺少 workflow_id"
            elif not enabled:
                item["blocking_reason"] = "工作流已创建，但启用返回未确认 status=enabled"
            else:
                item["blocking_reason"] = ""
            report.append(
                {
                    "surface": "workflow",
                    "name": str(item.get("name") or ""),
                    "status": item["lifecycle_state"],
                    "object_id": workflow_id,
                    "summary": str(spec.get("summary") or ""),
                }
            )
        except Exception as exc:
            item["lifecycle_state"] = _error_state(exc)
            item["blocking_reason"] = str(exc)
            report.append({"surface": "workflow", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "error": str(exc)})


async def _apply_automations(
    app_token: str,
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    force: bool,
    applied_at: int,
) -> None:
    specs = build_automation_specs()
    for item, spec in zip(_asset_list(assets, "automation_templates"), specs):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "automation", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        try:
            resp = await cli_base("+workflow-create", "--base-token", app_token, "--json", _json(spec["body"]))
            data = _resp_data(resp)
            workflow_id = str(data.get("workflow_id") or "")
            enabled = False
            if workflow_id:
                enable_resp = await cli_base("+workflow-enable", "--base-token", app_token, "--workflow-id", workflow_id)
                enabled = _workflow_enabled(_resp_data(enable_resp), workflow_id)
            item["lifecycle_state"] = "created" if workflow_id and enabled else "manual_finish_required"
            item["cloud_object_id"] = workflow_id
            item["applied_at"] = applied_at
            item["next_step"] = "继续在飞书工作流中把消息、任务、审批和负责人映射替换为真实业务动作"
            if not workflow_id:
                item["blocking_reason"] = "自动化 scaffold 创建后未返回 workflow_id"
            elif not enabled:
                item["blocking_reason"] = "自动化 scaffold 已创建，但启用返回未确认 status=enabled"
            else:
                item["blocking_reason"] = ""
            report.append(
                {
                    "surface": "automation",
                    "name": str(item.get("name") or ""),
                    "status": item["lifecycle_state"],
                    "object_id": workflow_id,
                    "summary": str(spec.get("summary") or ""),
                }
            )
        except Exception as exc:
            item["lifecycle_state"] = _error_state(exc)
            item["blocking_reason"] = str(exc)
            report.append({"surface": "automation", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "error": str(exc)})


async def _apply_dashboards(
    app_token: str,
    table_ids: dict[str, str],
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    force: bool,
    applied_at: int,
) -> None:
    dashboard_specs = build_dashboard_specs()
    for item, spec in zip(_asset_list(assets, "dashboard_blueprints"), dashboard_specs):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "dashboard", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        try:
            created = await cli_base(
                "+dashboard-create",
                "--base-token",
                app_token,
                "--name",
                str(spec["name"]),
                "--theme-style",
                "SimpleBlue",
            )
            data = _resp_data(created)
            dashboard_id = str(data.get("dashboard_id") or "")
            created_block_count = 0
            if dashboard_id:
                for _, block_name, block_type, block_config in spec["block_specs"]:
                    normalized = _normalize_block_config(block_config, table_ids, table_ids["task"])
                    block_resp = await cli_base(
                        "+dashboard-block-create",
                        "--base-token",
                        app_token,
                        "--dashboard-id",
                        dashboard_id,
                        "--name",
                        block_name,
                        "--type",
                        block_type,
                        "--data-config",
                        _json(normalized),
                    )
                    block_id = str((_resp_data(block_resp).get("block") or {}).get("block_id") or "")
                    if block_id:
                        created_block_count += 1
                if created_block_count:
                    await cli_base("+dashboard-arrange", "--base-token", app_token, "--dashboard-id", dashboard_id)
            expected_block_count = len(spec["block_specs"])
            dashboard_ready = bool(dashboard_id) and created_block_count == expected_block_count
            item["lifecycle_state"] = "created" if dashboard_ready else "manual_finish_required"
            item["cloud_object_id"] = dashboard_id
            item["cloud_block_count"] = created_block_count
            item["applied_at"] = applied_at
            item["next_step"] = "可继续在飞书仪表盘中补更多图表块并按需智能重排"
            if not dashboard_id:
                item["blocking_reason"] = "仪表盘创建返回中缺少 dashboard_id"
            elif created_block_count != expected_block_count:
                item["blocking_reason"] = f"仪表盘 block 创建不完整：期望 {expected_block_count}，实际 {created_block_count}"
            else:
                item["blocking_reason"] = ""
            report.append(
                {
                    "surface": "dashboard",
                    "name": str(item.get("name") or ""),
                    "status": item["lifecycle_state"],
                    "object_id": dashboard_id,
                    "block_count": item.get("cloud_block_count", 0),
                    "expected_block_count": expected_block_count,
                    "summary": str(spec.get("narrative") or ""),
                }
            )
        except Exception as exc:
            item["lifecycle_state"] = _error_state(exc)
            item["blocking_reason"] = str(exc)
            report.append({"surface": "dashboard", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "error": str(exc)})


async def _apply_roles(
    app_token: str,
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    force: bool,
    applied_at: int,
) -> None:
    role_specs = build_role_specs()
    for item, spec in zip(_asset_list(assets, "role_blueprints"), role_specs):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "role", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        try:
            resp = await cli_base("+role-create", "--base-token", app_token, "--json", _json(spec["config"]))
            success = _resp_success(_resp_data(resp))
            item["lifecycle_state"] = "created" if success else "manual_finish_required"
            item["applied_at"] = applied_at
            item["next_step"] = "继续在飞书中给该角色分配成员，并细化字段/视图级权限"
            item["blocking_reason"] = "" if success else "角色创建返回未确认 success=true"
            report.append(
                {
                    "surface": "role",
                    "name": str(item.get("name") or ""),
                    "status": item["lifecycle_state"],
                    "summary": str(spec.get("native_goal") or ""),
                }
            )
        except Exception as exc:
            item["lifecycle_state"] = _error_state(exc)
            item["blocking_reason"] = str(exc)
            report.append({"surface": "role", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "error": str(exc)})


def _mark_roles_waiting_advperm(
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    applied_at: int,
) -> None:
    for item in _asset_list(assets, "role_blueprints"):
        item["lifecycle_state"] = "manual_finish_required"
        item["applied_at"] = applied_at
        item["blocking_reason"] = "高级权限未确认启用，已跳过角色创建"
        report.append(
            {
                "surface": "role",
                "name": str(item.get("name") or ""),
                "status": "skipped",
                "reason": "advperm_not_ready",
            }
        )


def _asset_list(assets: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = assets.get(key) or []
    return value if isinstance(value, list) else []


def _sync_named_assets(assets: dict[str, Any], key: str, specs: list[dict[str, Any]], *, surface: str) -> None:
    existing = _asset_list(assets, key)
    existing_by_name = {str(item.get("name") or ""): item for item in existing if str(item.get("name") or "").strip()}
    synced: list[dict[str, Any]] = []
    for spec in specs:
        name = str(spec.get("name") or "").strip()
        defaults = _native_asset_defaults(surface, spec)
        current = copy.deepcopy(existing_by_name.get(name) or {})
        if not current:
            current = dict(defaults)
        else:
            for field_name, field_value in defaults.items():
                if field_name not in current or current.get(field_name) in (None, "", [], {}):
                    current[field_name] = copy.deepcopy(field_value)
            current.setdefault("status", str(current.get("lifecycle_state") or "blueprint_ready"))
            current.setdefault("lifecycle_state", "blueprint_ready")
        synced.append(current)
    assets[key] = synced


def _sync_form_assets(assets: dict[str, Any]) -> None:
    existing = _asset_list(assets, "form_blueprints")
    form_spec = build_form_spec()
    defaults = _form_asset_defaults(form_spec)
    if existing:
        merged = copy.deepcopy(existing[0])
        for field_name, field_value in defaults.items():
            if field_name not in merged or merged.get(field_name) in (None, "", [], {}):
                merged[field_name] = copy.deepcopy(field_value)
        merged.setdefault("status", str(merged.get("lifecycle_state") or "manual_finish_required"))
        merged.setdefault("lifecycle_state", "manual_finish_required")
        assets["form_blueprints"] = [merged]
        return
    assets["form_blueprints"] = [defaults]


def _native_asset_defaults(surface: str, spec: dict[str, Any]) -> dict[str, Any]:
    base = {
        "name": str(spec.get("name") or ""),
        "status": "blueprint_ready",
        "lifecycle_state": "blueprint_ready",
        "native_surface": surface,
        "delivery_mode": "manual_native_config",
        "api_readiness": "not_connected",
        "next_step": "",
        "blocking_reason": "",
    }
    if surface == "automation":
        base.update(
            {
                "trigger": spec.get("trigger", ""),
                "condition": spec.get("condition", ""),
                "action": spec.get("action", ""),
                "primary_field": spec.get("primary_field", ""),
                "summary": spec.get("summary", ""),
                "receiver_binding_fields": copy.deepcopy(spec.get("receiver_binding_fields", [])),
                "owner_binding_fields": copy.deepcopy(spec.get("owner_binding_fields", [])),
                "requires_member_binding": bool(spec.get("requires_member_binding")),
            }
        )
    elif surface == "workflow":
        base.update(
            {
                "entry_condition": spec.get("entry_condition", ""),
                "route_field": spec.get("route_field", ""),
                "actions": copy.deepcopy(spec.get("actions", [])),
                "summary": spec.get("summary", ""),
                "receiver_binding_fields": copy.deepcopy(spec.get("receiver_binding_fields", [])),
                "requires_member_binding": bool(spec.get("requires_member_binding")),
            }
        )
    elif surface == "dashboard":
        base.update(
            {
                "focus_metrics": copy.deepcopy(spec.get("focus_metrics", [])),
                "recommended_views": copy.deepcopy(spec.get("recommended_views", [])),
                "narrative": spec.get("narrative", ""),
                "block_count": len(spec.get("block_specs") or []),
            }
        )
    elif surface == "role":
        base.update(
            {
                "focus_views": copy.deepcopy(spec.get("focus_views", [])),
                "permissions_focus": copy.deepcopy(spec.get("permissions_focus", [])),
                "dashboard_focus": copy.deepcopy(spec.get("dashboard_focus", [])),
            }
        )
    return base


def _form_asset_defaults(form_spec: dict[str, Any]) -> dict[str, Any]:
    questions = copy.deepcopy(form_spec["questions"])
    return {
        "name": str(form_spec["name"]),
        "status": "manual_share_required",
        "lifecycle_state": "manual_finish_required",
        "native_surface": "form",
        "delivery_mode": "setup_created_view",
        "api_readiness": "connected",
        "next_step": "在飞书 UI 中开启表单共享，拿到可直接投递的链接",
        "blocking_reason": "表单蓝图尚未同步共享链接",
        "shared_url": "",
        "entry_fields": [str(question["title"]) for question in questions],
        "question_count": len(questions),
        "questions": questions,
        "description": str(form_spec["description"]),
    }


def _advperm_items(assets: dict[str, Any]) -> list[dict[str, Any]]:
    items = _asset_list(assets, "advperm_blueprints")
    if items:
        state = str(assets.get("advperm_state") or items[0].get("lifecycle_state") or "blueprint_ready")
        items[0]["lifecycle_state"] = state
        return items
    state = str(assets.get("advperm_state") or "blueprint_ready")
    synthesized = {
        "name": "Base 高级权限",
        "lifecycle_state": state,
        "native_surface": "advperm",
        "delivery_mode": "manual_native_config",
        "api_readiness": "not_connected",
    }
    assets["advperm_blueprints"] = [synthesized]
    return assets["advperm_blueprints"]


def _resp_data(resp: dict[str, Any]) -> dict[str, Any]:
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


def _resp_success(data: dict[str, Any]) -> bool:
    return bool(data.get("success") is True)


def _workflow_enabled(data: dict[str, Any], workflow_id: str) -> bool:
    return str(data.get("workflow_id") or "") == workflow_id and str(data.get("status") or "").lower() == "enabled"


def _error_state(exc: Exception) -> str:
    text = str(exc).lower()
    return "permission_blocked" if "permission" in text or "scope" in text or "auth" in text else "manual_finish_required"


def _json(obj: dict[str, Any]) -> str:
    return __import__("json").dumps(obj, ensure_ascii=False)


def _table_name_by_id(table_ids: dict[str, str], table_id: str) -> str:
    mapping = {
        table_ids.get("task"): "分析任务",
        table_ids.get("output"): "岗位分析",
        table_ids.get("report"): "综合报告",
        table_ids.get("performance"): "数字员工效能",
        table_ids.get("datasource"): "📚 数据源库",
        table_ids.get("evidence"): "证据链",
        table_ids.get("review"): "产出评审",
        table_ids.get("action"): "交付动作",
        table_ids.get("review_history"): "复核历史",
        table_ids.get("archive"): "交付结果归档",
        table_ids.get("automation_log"): "自动化日志",
        table_ids.get("template"): "模板配置中心",
    }
    return mapping.get(table_id, "分析任务")


def _normalize_block_config(block_config: dict[str, Any], table_ids: dict[str, str], source_table_id: str) -> dict[str, Any]:
    normalized = copy.deepcopy(block_config)
    if normalized.get("table_name") == "AUTO":
        normalized["table_name"] = _table_name_by_id(table_ids, source_table_id)
    return normalized


def _refresh_native_assets(assets: dict[str, Any]) -> None:
    sync_native_asset_blueprints(assets)
    groups = [
        {"key": "advperm", "label": "高级权限", "items": _advperm_items(assets)},
        {"key": "forms", "label": "表单入口", "items": _asset_list(assets, "form_blueprints")},
        {"key": "automations", "label": "自动化模板", "items": _asset_list(assets, "automation_templates")},
        {"key": "workflows", "label": "工作流蓝图", "items": _asset_list(assets, "workflow_blueprints")},
        {"key": "dashboards", "label": "仪表盘蓝图", "items": _asset_list(assets, "dashboard_blueprints")},
        {"key": "roles", "label": "角色蓝图", "items": _asset_list(assets, "role_blueprints")},
    ]
    priority = {
        "permission_blocked": 5,
        "manual_finish_required": 4,
        "blueprint_ready": 3,
        "api_supported": 2,
        "created": 1,
    }
    counts = {key: 0 for key in ["created", "api_supported", "blueprint_ready", "manual_finish_required", "permission_blocked"]}
    group_states: list[dict[str, Any]] = []
    overall_state = "created"
    for group in groups:
        group_counts = {key: 0 for key in counts}
        group_state = "created"
        for item in group["items"]:
            state = str(item.get("lifecycle_state") or "blueprint_ready")
            if state not in counts:
                state = "blueprint_ready"
            counts[state] += 1
            group_counts[state] += 1
            if priority[state] > priority[group_state]:
                group_state = state
            if priority[state] > priority[overall_state]:
                overall_state = state
        group_states.append({"key": group["key"], "label": group["label"], "count": len(group["items"]), "state": group_state, "counts": group_counts})

    assets["overall_state"] = overall_state
    assets["status"] = overall_state
    assets["status_summary"] = {
        "overall_state": overall_state,
        "counts": counts,
        "total_assets": sum(counts.values()),
        "groups": group_states,
    }
    assets["asset_groups"] = group_states

    checklist = _asset_list(assets, "manual_finish_checklist")
    form_items = _asset_list(assets, "form_blueprints")
    automation_items = _asset_list(assets, "automation_templates")
    workflow_items = _asset_list(assets, "workflow_blueprints")
    dashboard_items = _asset_list(assets, "dashboard_blueprints")
    role_items = _asset_list(assets, "role_blueprints")
    form_state = _group_state(form_items)
    automation_state = _group_state(automation_items)
    workflow_state = _group_state(workflow_items)
    dashboard_state = _group_state(dashboard_items)
    role_state = _group_state(role_items)
    advperm_state = str(assets.get("advperm_state") or "blueprint_ready")
    form_done = any(str(item.get("shared_url") or "").strip() for item in form_items)
    automation_done = bool(automation_items) and all(str(item.get("lifecycle_state") or "") == "created" for item in automation_items)
    workflow_done = bool(workflow_items) and all(str(item.get("lifecycle_state") or "") == "created" for item in workflow_items)
    dashboard_done = bool(dashboard_items) and all(str(item.get("lifecycle_state") or "") == "created" for item in dashboard_items)
    role_done = bool(role_items) and all(str(item.get("lifecycle_state") or "") == "created" for item in role_items)
    if len(checklist) >= 6:
        checklist[0]["state"] = advperm_state
        checklist[0]["done"] = advperm_state == "created"
        checklist[1]["state"] = form_state
        checklist[1]["done"] = form_done
        checklist[2]["state"] = automation_state
        checklist[2]["done"] = automation_done
        checklist[3]["state"] = workflow_state
        checklist[3]["done"] = workflow_done
        checklist[4]["state"] = dashboard_state
        checklist[4]["done"] = dashboard_done
        checklist[5]["state"] = role_state
        checklist[5]["done"] = role_done
    elif len(checklist) >= 5:
        checklist[0]["state"] = form_state
        checklist[0]["done"] = form_done
        checklist[1]["state"] = automation_state
        checklist[1]["done"] = automation_done
        checklist[2]["state"] = workflow_state
        checklist[2]["done"] = workflow_done
        checklist[3]["state"] = dashboard_state
        checklist[3]["done"] = dashboard_done
        checklist[4]["state"] = role_state
        checklist[4]["done"] = role_done


async def _write_native_install_logs(
    *,
    app_token: str,
    automation_log_tid: str | None,
    report: list[dict[str, Any]],
    base_meta: dict[str, Any],
    applied_at: int,
) -> None:
    if not automation_log_tid:
        return
    for item in report:
        status = str(item.get("status") or "manual_finish_required")
        mapped_status = _automation_log_status(status)
        detail_parts = [
            f"surface={item.get('surface', '')}",
            f"status={status}",
            f"base_type={base_meta.get('base_type', '')}",
            f"mode={base_meta.get('mode', '')}",
            f"applied_at={applied_at}",
        ]
        if item.get("object_id"):
            detail_parts.append(f"object_id={item.get('object_id')}")
        if item.get("block_count") is not None:
            detail_parts.append(f"block_count={item.get('block_count')}")
        if item.get("expected_block_count") is not None:
            detail_parts.append(f"expected_block_count={item.get('expected_block_count')}")
        if item.get("reason"):
            detail_parts.append(f"reason={item.get('reason')}")
        if item.get("error"):
            detail_parts.append(f"error={item.get('error')}")
        fields = {
            "日志标题": f"原生安装 · {str(item.get('name') or item.get('surface') or '未命名步骤')}",
            "任务标题": "飞书原生安装包",
            "节点名称": str(item.get("name") or item.get("surface") or "native"),
            "触发来源": "native_manifest.apply",
            "执行状态": mapped_status,
            "工作流路由": "直接执行",
            "日志摘要": truncate_with_marker(
                str(item.get("error") or item.get("reason") or item.get("object_id") or status),
                500,
                "...",
            ),
            "详细结果": truncate_with_marker("\n".join(detail_parts), 1800, "\n...[已截断]"),
            "关联记录ID": str(item.get("object_id") or ""),
        }
        try:
            await bitable_ops.create_record_optional_fields(
                app_token,
                automation_log_tid,
                fields,
                optional_keys=["工作流路由", "详细结果", "关联记录ID"],
            )
        except Exception as exc:
            logger.warning("write native install automation log failed item=%s: %s", item.get("name"), exc)


def _group_state(items: list[dict[str, Any]]) -> str:
    if not items:
        return "blueprint_ready"
    priority = {
        "permission_blocked": 5,
        "manual_finish_required": 4,
        "blueprint_ready": 3,
        "api_supported": 2,
        "created": 1,
    }
    state = "created"
    for item in items:
        current = str(item.get("lifecycle_state") or "blueprint_ready")
        if current not in priority:
            current = "blueprint_ready"
        if priority[current] > priority[state]:
            state = current
    return state


def _automation_log_status(status: str) -> str:
    if status == "created":
        return "已完成"
    if status == "skipped":
        return "已跳过"
    if status == "manual_finish_required":
        return "待补完"
    return "执行失败"
