"""Execute Feishu-native installation steps for the current Base."""

from __future__ import annotations

import copy
import logging
import time
from typing import Any

from app.bitable_workflow.native_manifest import build_native_manifest
from app.feishu.cli_bridge import cli_base, is_cli_available

logger = logging.getLogger(__name__)

_ALL_SURFACES = {"form", "workflow", "dashboard", "role"}


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
    if "workflow" in targets:
        await _apply_workflows(app_token, assets, report, force=force, applied_at=applied_at)
    if "dashboard" in targets:
        await _apply_dashboards(app_token, table_ids, assets, report, force=force, applied_at=applied_at)
    if "role" in targets:
        await _apply_roles(app_token, assets, report, force=force, applied_at=applied_at)

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
    bodies = [
        _workflow_body("W1 路由总分发工作流", "分析任务", "状态"),
        _workflow_body("W2 拍板分支工作流", "分析任务", "当前责任角色"),
        _workflow_body("W3 执行分支工作流", "分析任务", "当前责任角色"),
    ]
    for item, body in zip(_asset_list(assets, "workflow_blueprints"), bodies):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "workflow", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        try:
            resp = await cli_base("+workflow-create", "--base-token", app_token, "--json", _json(body))
            data = _resp_data(resp)
            workflow_id = str(data.get("workflow_id") or "")
            if workflow_id:
                await cli_base("+workflow-enable", "--base-token", app_token, "--workflow-id", workflow_id)
            item["lifecycle_state"] = "created" if workflow_id else "manual_finish_required"
            item["cloud_object_id"] = workflow_id
            item["applied_at"] = applied_at
            item["next_step"] = "如需更强业务逻辑，可继续在飞书工作流里扩展触发条件和动作"
            item["blocking_reason"] = "" if workflow_id else "工作流创建返回中缺少 workflow_id"
            report.append({"surface": "workflow", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "object_id": workflow_id})
        except Exception as exc:
            item["lifecycle_state"] = _error_state(exc)
            item["blocking_reason"] = str(exc)
            report.append({"surface": "workflow", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "error": str(exc)})


async def _apply_dashboards(
    app_token: str,
    table_ids: dict[str, str],
    assets: dict[str, Any],
    report: list[dict[str, Any]],
    *,
    force: bool,
    applied_at: int,
) -> None:
    dashboard_specs = [
        ("管理汇报总览", table_ids["task"], "分析任务总量", "工作流路由、待拍板、待执行、异常任务一屏汇总"),
        ("证据与评审看板", table_ids.get("evidence", table_ids["task"]), "证据链总量", "围绕硬证据、待验证、CEO 汇总构建原生证据看板"),
        ("交付异常看板", table_ids["task"], "异常任务总量", "围绕拍板滞留、执行超期、复核超时、复盘滞留构建异常雷达"),
    ]
    for item, spec in zip(_asset_list(assets, "dashboard_blueprints"), dashboard_specs):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "dashboard", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        name, source_table_id, stat_name, text_body = spec
        try:
            created = await cli_base(
                "+dashboard-create",
                "--base-token",
                app_token,
                "--name",
                name,
                "--theme-style",
                "SimpleBlue",
            )
            data = _resp_data(created)
            dashboard_id = str(data.get("dashboard_id") or "")
            if dashboard_id:
                await cli_base(
                    "+dashboard-block-create",
                    "--base-token",
                    app_token,
                    "--dashboard-id",
                    dashboard_id,
                    "--name",
                    stat_name,
                    "--type",
                    "statistics",
                    "--data-config",
                    _json({"table_name": _table_name_by_id(table_ids, source_table_id), "count_all": True}),
                )
                await cli_base(
                    "+dashboard-block-create",
                    "--base-token",
                    app_token,
                    "--dashboard-id",
                    dashboard_id,
                    "--name",
                    "看板说明",
                    "--type",
                    "text",
                    "--data-config",
                    _json({"text": f"# {name}\n\n{text_body}"}),
                )
            item["lifecycle_state"] = "created" if dashboard_id else "manual_finish_required"
            item["cloud_object_id"] = dashboard_id
            item["applied_at"] = applied_at
            item["next_step"] = "可继续在飞书仪表盘中补更多图表块并按需智能重排"
            item["blocking_reason"] = "" if dashboard_id else "仪表盘创建返回中缺少 dashboard_id"
            report.append({"surface": "dashboard", "name": str(item.get("name") or ""), "status": item["lifecycle_state"], "object_id": dashboard_id})
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
    role_specs = [
        _role_body("高管交付面", ["分析任务", "综合报告", "交付动作"]),
        _role_body("执行负责人工作面", ["分析任务", "交付动作", "交付结果归档"]),
        _role_body("复核负责人工作面", ["分析任务", "证据链", "产出评审", "复核历史"]),
    ]
    for item, body in zip(_asset_list(assets, "role_blueprints"), role_specs):
        if not force and str(item.get("lifecycle_state") or "") == "created":
            report.append({"surface": "role", "name": str(item.get("name") or ""), "status": "skipped", "reason": "already_created"})
            continue
        try:
            await cli_base("+role-create", "--base-token", app_token, "--json", _json(body))
            item["lifecycle_state"] = "created"
            item["applied_at"] = applied_at
            item["next_step"] = "继续在飞书中给该角色分配成员，并细化字段/视图级权限"
            item["blocking_reason"] = ""
            report.append({"surface": "role", "name": str(item.get("name") or ""), "status": "created"})
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


def _workflow_body(title: str, table_name: str, watched_field_name: str) -> dict[str, Any]:
    token = str(int(time.time() * 1000))
    return {
        "client_token": token,
        "title": title,
        "steps": [
            {
                "id": "step_trigger",
                "type": "AddRecordTrigger",
                "title": "新增记录时触发",
                "next": "step_notify",
                "data": {
                    "table_name": table_name,
                    "watched_field_name": watched_field_name,
                    "condition_list": None,
                },
            },
            {
                "id": "step_notify",
                "type": "LarkMessageAction",
                "title": "发送原生工作流提示",
                "next": None,
                "data": {
                    "receiver": [],
                    "send_to_everyone": True,
                    "title": [{"value_type": "text", "value": title}],
                    "content": [{"value_type": "text", "value": "该工作流已由多 Agent 交付系统自动创建，请在飞书工作流中继续补齐真实业务动作。"}],
                    "btn_list": [],
                },
            },
        ],
    }


def _role_body(role_name: str, table_names: list[str]) -> dict[str, Any]:
    return {
        "role_name": role_name,
        "role_type": "custom_role",
        "base_rule_map": {
            "copy": False,
            "download": False,
        },
        "table_rule_map": {table_name: {"perm": "read_only"} for table_name in table_names},
    }


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
