"""Build copy-ready Feishu native installation packs for the current Base."""

from __future__ import annotations

import json
import shlex
from typing import Any

from app.bitable_workflow.native_specs import (
    build_automation_specs,
    build_dashboard_specs,
    build_form_spec,
    build_role_specs,
    build_workflow_specs,
)


def build_native_manifest(
    *,
    app_token: str,
    base_url: str,
    table_ids: dict[str, str],
    base_meta: dict[str, Any],
    native_assets: dict[str, Any],
) -> dict[str, Any]:
    automation_specs = build_automation_specs()
    workflow_specs = build_workflow_specs()
    dashboard_specs = build_dashboard_specs()
    role_specs = build_role_specs()
    form_spec = build_form_spec()
    install_order = [
        {
            "step": 1,
            "title": "启用高级权限",
            "surface": "advperm",
            "why": "角色工作面和高级权限依赖先启用 Base 高级权限。",
        },
        {
            "step": 2,
            "title": "补齐任务收集表单",
            "surface": "form",
            "why": "让业务方从原生表单直接进入主表，不再只靠驾驶舱录入。",
        },
        {
            "step": 3,
            "title": "创建自动化与消息分发 scaffold",
            "surface": "automation",
            "why": "把入场提醒、自动汇报、执行创建、复核提醒、异常升级都推进成飞书原生触发器。",
        },
        {
            "step": 4,
            "title": "创建路由与责任工作流",
            "surface": "workflow",
            "why": "让拍板、执行和交付路由真正交给飞书工作流，而不是仅靠 API 回写。",
        },
        {
            "step": 5,
            "title": "创建管理仪表盘与异常雷达",
            "surface": "dashboard",
            "why": "把管理总览、证据评审、异常压盘放回飞书原生可视化层。",
        },
        {
            "step": 6,
            "title": "创建角色与权限工作面",
            "surface": "role",
            "why": "确保高管、执行、复核在 Base 内各看各的原生工作面。",
        },
    ]

    command_packs = [
        {
            "key": "advperm",
            "label": "高级权限",
            "surface": "advperm",
            "status": _advperm_state(native_assets),
            "commands": [
                f"lark-cli base +advperm-enable --base-token {app_token}",
            ],
            "notes": [
                "执行用户必须是 Base 管理员。",
                "启用后才能继续创建自定义角色。",
            ],
        },
        {
            "key": "form",
            "label": "原生表单",
            "surface": "form",
            "status": _form_pack_state(native_assets),
            "commands": _form_commands(app_token, table_ids["task"], form_spec),
            "notes": [
                "当前 setup 已创建表单视图；这里补的是独立表单对象与题目。",
                "命令包已经带题目 JSON，只差真实 form_id 和共享动作。",
            ],
            "json_body": form_spec,
        },
        {
            "key": "automation",
            "label": "自动化 scaffold",
            "surface": "automation",
            "status": _surface_state(native_assets, "automation"),
            "commands": _workflow_create_commands(app_token, automation_specs),
            "notes": [
                "这里用 workflow scaffold 承接自动化模板，避免自动化永远停在 blueprint 状态。",
                "每个自动化都已经带上任务责任面回写、消息提醒和日志/动作沉淀骨架。",
            ],
            "json_bodies": [spec["body"] for spec in automation_specs],
        },
        {
            "key": "workflow",
            "label": "路由工作流",
            "surface": "workflow",
            "status": _surface_state(native_assets, "workflow"),
            "commands": _workflow_create_commands(app_token, workflow_specs),
            "notes": [
                "创建后建议立即启用，并继续补成员映射、审批链和任务动作。",
                "当前 JSON 不只是提示消息，而是带主表状态回写、动作沉淀和日志记录骨架。",
            ],
            "json_bodies": [spec["body"] for spec in workflow_specs],
        },
        {
            "key": "dashboard",
            "label": "管理仪表盘",
            "surface": "dashboard",
            "status": _surface_state(native_assets, "dashboard"),
            "commands": _dashboard_commands(app_token, dashboard_specs),
            "notes": [
                "每个仪表盘都带可直接落地的 block 配置，按顺序串行创建即可。",
                "优先级最高的是管理汇报总览，其次是证据与评审、交付异常压盘。",
            ],
        },
        {
            "key": "role",
            "label": "角色权限",
            "surface": "role",
            "status": _surface_state(native_assets, "role"),
            "commands": _role_commands(app_token, role_specs),
            "notes": [
                "角色配置里已经带了 dashboard_rule_map、view_rule 和 edit/read 工作面差异。",
                "创建后只需要继续分配真实成员，而不是从零写权限 JSON。",
            ],
            "json_bodies": [spec["config"] for spec in role_specs],
        },
    ]

    markdown = _manifest_markdown(
        app_token=app_token,
        base_url=base_url,
        base_meta=base_meta,
        native_assets=native_assets,
        install_order=install_order,
        command_packs=command_packs,
    )

    return {
        "manifest_version": "v2",
        "app_token": app_token,
        "base_url": base_url,
        "base_meta": base_meta,
        "install_order": install_order,
        "command_packs": command_packs,
        "markdown": markdown,
    }

def _workflow_create_commands(app_token: str, specs: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for spec in specs:
        commands.append(f"# {spec['name']}")
        commands.append(
            " ".join(
                [
                    "lark-cli base +workflow-create",
                    f"--base-token {_shell_arg(app_token)}",
                    f"--json {_json_arg(spec['body'])}",
                ]
            )
        )
    return commands


def _form_commands(app_token: str, table_id: str, spec: dict[str, Any]) -> list[str]:
    return [
        " ".join(
            [
                "lark-cli base +form-create",
                f"--base-token {_shell_arg(app_token)}",
                f"--table-id {_shell_arg(table_id)}",
                f"--name {_shell_arg(spec['name'])}",
                f"--description {_shell_arg(spec['description'])}",
            ]
        ),
        "# 记录上一步返回的 <form_id>，再创建题目：",
        " ".join(
            [
                "lark-cli base +form-questions-create",
                f"--base-token {_shell_arg(app_token)}",
                f"--table-id {_shell_arg(table_id)}",
                "--form-id <form_id>",
                f"--questions {_json_arg(spec['questions'])}",
            ]
        ),
    ]


def _dashboard_commands(app_token: str, specs: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for spec in specs:
        commands.append(f"# {spec['name']}")
        commands.append(
            " ".join(
                [
                    "lark-cli base +dashboard-create",
                    f"--base-token {_shell_arg(app_token)}",
                    f"--name {_shell_arg(spec['name'])}",
                    "--theme-style SimpleBlue",
                ]
            )
        )
        commands.append("# 创建后按 block_specs 顺序串行执行 +dashboard-block-create，再调用 +dashboard-arrange")
    return commands


def _role_commands(app_token: str, specs: list[dict[str, Any]]) -> list[str]:
    commands: list[str] = []
    for spec in specs:
        commands.append(f"# {spec['name']}")
        commands.append(
            " ".join(
                [
                    "lark-cli base +role-create",
                    f"--base-token {_shell_arg(app_token)}",
                    f"--json {_json_arg(spec['config'])}",
                ]
            )
        )
    return commands


def _shell_arg(value: Any) -> str:
    return shlex.quote(str(value))


def _json_arg(value: Any) -> str:
    return shlex.quote(json.dumps(value, ensure_ascii=False))


def _manifest_markdown(
    *,
    app_token: str,
    base_url: str,
    base_meta: dict[str, Any],
    native_assets: dict[str, Any],
    install_order: list[dict[str, Any]],
    command_packs: list[dict[str, Any]],
) -> str:
    lines = [
        "# 飞书多维表格原生安装包",
        "",
        "## Base 信息",
        "",
        f"- Base Token: `{app_token}`",
        f"- Base URL: {base_url}",
        f"- Base 类型: `{base_meta.get('base_type', '')}`",
        f"- 初始化模式: `{base_meta.get('mode', '')}`",
        f"- Schema 版本: `{base_meta.get('schema_version', '')}`",
        f"- 当前原生资产状态: `{native_assets.get('overall_state', native_assets.get('status', 'unknown'))}`",
        "",
        "## 安装顺序",
        "",
    ]
    for item in install_order:
        lines.append(f"{item['step']}. {item['title']}：{item['why']}")

    lines.extend(["", "## 命令包", ""])
    for pack in command_packs:
        lines.append(f"### {pack['label']}")
        lines.append("")
        lines.append(f"- 当前状态：`{pack['status']}`")
        for note in pack.get("notes", []):
            lines.append(f"- {note}")
        lines.append("")
        lines.append("```bash")
        for command in pack.get("commands", []):
            lines.append(command)
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _surface_state(native_assets: dict[str, Any], surface: str) -> str:
    key_map = {
        "form": "form_blueprints",
        "automation": "automation_templates",
        "workflow": "workflow_blueprints",
        "dashboard": "dashboard_blueprints",
        "role": "role_blueprints",
    }
    items = native_assets.get(key_map[surface]) or []
    if not isinstance(items, list) or not items:
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
        current = str((item or {}).get("lifecycle_state") or "blueprint_ready")
        if current not in priority:
            current = "blueprint_ready"
        if priority[current] > priority[state]:
            state = current
    return state


def _advperm_state(native_assets: dict[str, Any]) -> str:
    state = str(native_assets.get("advperm_state") or "").strip()
    if state:
        return state
    return _surface_state(native_assets, "role")


def _form_pack_state(native_assets: dict[str, Any]) -> str:
    forms = native_assets.get("form_blueprints") or []
    if not isinstance(forms, list) or not forms:
        return "manual_finish_required"
    form = forms[0] or {}
    if str(form.get("cloud_object_id") or "").strip():
        return str(form.get("lifecycle_state") or "created")
    return "manual_finish_required"
