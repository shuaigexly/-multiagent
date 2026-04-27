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
    build_role_specs,
    build_workflow_specs,
)
from app.core.text_utils import truncate_with_marker
from app.feishu.cli_bridge import cli_base, is_cli_available

logger = logging.getLogger(__name__)

_ALL_SURFACES = {"form", "automation", "workflow", "dashboard", "role"}


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
    report: list[dict[str, Any]] = []

    if not is_cli_available():
        raise RuntimeError("lark-cli 不可用，无法执行飞书原生安装")

    applied_at = int(time.time())

    if "role" in targets:
        await _apply_advperm(app_token, report)

    if "form" in targets:
        await _apply_form(app_token, table_ids, assets, report, force=force, applied_at=applied_at)
    if "automation" in targets:
        await _apply_automations(app_token, assets, report, force=force, applied_at=applied_at)
    if "workflow" in targets:
        await _apply_workflows(app_token, assets, report, force=force, applied_at=applied_at)
    if "dashboard" in targets:
        await _apply_dashboards(app_token, table_ids, assets, report, force=force, applied_at=applied_at)
    if "role" in targets:
        await _apply_roles(app_token, assets, report, force=force, applied_at=applied_at)

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


async def _apply_advperm(app_token: str, report: list[dict[str, Any]]) -> None:
    try:
        resp = await cli_base("+advperm-enable", "--base-token", app_token)
        report.append({"surface": "role", "name": "启用高级权限", "status": "created", "response": resp})
    except Exception as exc:
        logger.warning("advperm enable failed: %s", exc)
        report.append({"surface": "role", "name": "启用高级权限", "status": _error_state(exc), "error": str(exc)})


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
    if not force and str(form.get("lifecycle_state") or "") == "created":
        report.append({"surface": "form", "name": str(form.get("name") or "任务收集表单"), "status": "skipped", "reason": "already_created"})
        return
    try:
        resp = await cli_base(
            "+form-create",
            "--base-token",
            app_token,
            "--table-id",
            table_ids["task"],
            "--name",
            "任务收集表单",
        )
        data = _resp_data(resp)
        form["lifecycle_state"] = "created"
        form["cloud_object_id"] = str(data.get("id") or "")
        form["applied_at"] = applied_at
        form["next_step"] = "继续在飞书 UI 中配置题目、说明和共享范围"
        form["blocking_reason"] = ""
        report.append({"surface": "form", "name": str(form.get("name") or "任务收集表单"), "status": "created", "object_id": form["cloud_object_id"]})
    except Exception as exc:
        form["lifecycle_state"] = _error_state(exc)
        form["blocking_reason"] = str(exc)
        report.append({"surface": "form", "name": str(form.get("name") or "任务收集表单"), "status": form["lifecycle_state"], "error": str(exc)})


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
            if workflow_id:
                await cli_base("+workflow-enable", "--base-token", app_token, "--workflow-id", workflow_id)
            item["lifecycle_state"] = "created" if workflow_id else "manual_finish_required"
            item["cloud_object_id"] = workflow_id
            item["applied_at"] = applied_at
            item["next_step"] = "如需更强业务逻辑，可继续在飞书工作流里补成员映射、审批链和任务卡片动作"
            item["blocking_reason"] = "" if workflow_id else "工作流创建返回中缺少 workflow_id"
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
            if workflow_id:
                await cli_base("+workflow-enable", "--base-token", app_token, "--workflow-id", workflow_id)
            item["lifecycle_state"] = "created" if workflow_id else "manual_finish_required"
            item["cloud_object_id"] = workflow_id
            item["applied_at"] = applied_at
            item["next_step"] = "继续在飞书工作流中把消息、任务、审批和负责人映射替换为真实业务动作"
            item["blocking_reason"] = "" if workflow_id else "自动化 scaffold 创建后未返回 workflow_id"
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
            if dashboard_id:
                created_blocks: list[str] = []
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
                        created_blocks.append(block_id)
                if created_blocks:
                    await cli_base("+dashboard-arrange", "--base-token", app_token, "--dashboard-id", dashboard_id)
            item["lifecycle_state"] = "created" if dashboard_id else "manual_finish_required"
            item["cloud_object_id"] = dashboard_id
            item["cloud_block_count"] = len(spec["block_specs"]) if dashboard_id else 0
            item["applied_at"] = applied_at
            item["next_step"] = "可继续在飞书仪表盘中补更多图表块并按需智能重排"
            item["blocking_reason"] = "" if dashboard_id else "仪表盘创建返回中缺少 dashboard_id"
            report.append(
                {
                    "surface": "dashboard",
                    "name": str(item.get("name") or ""),
                    "status": item["lifecycle_state"],
                    "object_id": dashboard_id,
                    "block_count": item.get("cloud_block_count", 0),
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
            await cli_base("+role-create", "--base-token", app_token, "--json", _json(spec["config"]))
            item["lifecycle_state"] = "created"
            item["applied_at"] = applied_at
            item["next_step"] = "继续在飞书中给该角色分配成员，并细化字段/视图级权限"
            item["blocking_reason"] = ""
            report.append(
                {
                    "surface": "role",
                    "name": str(item.get("name") or ""),
                    "status": "created",
                    "summary": str(spec.get("native_goal") or ""),
                }
            )
        except Exception as exc:
            item["lifecycle_state"] = _error_state(exc)
            item["blocking_reason"] = str(exc)
            report.append({"surface": "role", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "error": str(exc)})


def _asset_list(assets: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = assets.get(key) or []
    return value if isinstance(value, list) else []


def _resp_data(resp: dict[str, Any]) -> dict[str, Any]:
    data = resp.get("data")
    return data if isinstance(data, dict) else {}


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
    groups = [
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
    form_created = any(str(item.get("lifecycle_state") or "") == "created" for item in _asset_list(assets, "form_blueprints"))
    workflow_created = any(str(item.get("lifecycle_state") or "") == "created" for item in _asset_list(assets, "workflow_blueprints"))
    dashboard_created = any(str(item.get("lifecycle_state") or "") == "created" for item in _asset_list(assets, "dashboard_blueprints"))
    role_created = any(str(item.get("lifecycle_state") or "") == "created" for item in _asset_list(assets, "role_blueprints"))
    if len(checklist) >= 5:
        checklist[0]["done"] = form_created
        checklist[2]["done"] = workflow_created
        checklist[3]["done"] = dashboard_created
        checklist[4]["done"] = role_created


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
        mapped_status = "已完成" if status == "created" else "已跳过" if status == "skipped" else "执行失败"
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
