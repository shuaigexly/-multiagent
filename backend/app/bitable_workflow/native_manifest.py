"""Build copy-ready Feishu native installation packs for the current Base."""

from __future__ import annotations

import json
from typing import Any


def build_native_manifest(
    *,
    app_token: str,
    base_url: str,
    table_ids: dict[str, str],
    base_meta: dict[str, Any],
    native_assets: dict[str, Any],
) -> dict[str, Any]:
    workflow_body = _workflow_body(table_name="分析任务")
    role_body = _role_body()
    install_order = [
        {
            "step": 1,
            "title": "启用高级权限",
            "surface": "role",
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
            "title": "创建路由工作流",
            "surface": "workflow",
            "why": "让拍板、执行、复核真正交给飞书工作流，而不是仅靠 API 回写。",
        },
        {
            "step": 4,
            "title": "创建管理仪表盘与图表块",
            "surface": "dashboard",
            "why": "把管理总览、异常雷达、证据评审放回飞书原生可视化层。",
        },
        {
            "step": 5,
            "title": "创建角色与权限工作面",
            "surface": "role",
            "why": "确保高管、执行、复核在 Base 内各看各的原生工作面。",
        },
    ]

    command_packs = [
        {
            "key": "advperm",
            "label": "高级权限",
            "surface": "role",
            "status": "blueprint_ready",
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
            "status": "manual_finish_required",
            "commands": [
                f"lark-cli base +form-create --base-token {app_token} --table-id {table_ids['task']} --name '任务收集表单'",
            ],
            "notes": [
                "当前 setup 已创建表单视图；如需独立原生表单对象，可再执行此命令创建。",
                "创建后可继续在飞书中补题目、说明和共享范围。",
            ],
        },
        {
            "key": "workflow",
            "label": "路由工作流",
            "surface": "workflow",
            "status": "blueprint_ready",
            "commands": [
                f"lark-cli base +workflow-create --base-token {app_token} --json {json.dumps(workflow_body, ensure_ascii=False)}",
            ],
            "notes": [
                "创建后默认是 disabled，需再手动启用。",
                "当前 JSON 先给出主骨架，后续可按字段 ID/负责人映射继续细化。",
            ],
            "json_body": workflow_body,
        },
        {
            "key": "dashboard",
            "label": "管理仪表盘",
            "surface": "dashboard",
            "status": "blueprint_ready",
            "commands": [
                f"lark-cli base +dashboard-create --base-token {app_token} --name '多 Agent 交付总览' --theme-style SimpleBlue",
                "# 创建后继续用 +dashboard-block-create 添加统计卡、路由分布和异常雷达组件",
            ],
            "notes": [
                "先建空仪表盘，再串行创建图表块。",
                "推荐优先落 3 块：工作流路由分布、待拍板确认数、异常任务数。",
            ],
        },
        {
            "key": "role",
            "label": "角色权限",
            "surface": "role",
            "status": "blueprint_ready",
            "commands": [
                f"lark-cli base +role-create --base-token {app_token} --json {json.dumps(role_body, ensure_ascii=False)}",
            ],
            "notes": [
                "建议先创建高管角色，再派生执行与复核角色。",
                "更细的字段级权限与视图级权限，需要按真实业务成员继续补齐。",
            ],
            "json_body": role_body,
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
        "manifest_version": "v1",
        "app_token": app_token,
        "base_url": base_url,
        "base_meta": base_meta,
        "install_order": install_order,
        "command_packs": command_packs,
        "markdown": markdown,
    }


def _workflow_body(*, table_name: str) -> dict[str, Any]:
    return {
        "client_token": "replace-with-unique-token",
        "title": "分析任务原生路由工作流",
        "steps": [
            {
                "id": "trigger_1",
                "type": "AddRecordTrigger",
                "title": "监听分析任务写入",
                "next": "branch_1",
                "data": {
                    "table_name": table_name,
                    "watched_field_name": "状态",
                },
            },
            {
                "id": "branch_1",
                "type": "IfElseBranch",
                "title": "判断是否进入交付阶段",
                "next": None,
                "children": {
                    "links": [
                        {"condition": '状态 = "已完成"', "to": "action_1"},
                        {"condition": "default", "to": "action_2"},
                    ]
                },
                "data": {},
            },
            {
                "id": "action_1",
                "type": "LarkMessageAction",
                "title": "发送管理通知",
                "next": None,
                "data": {
                    "receiver": [],
                    "send_to_everyone": False,
                    "title": [{"value_type": "text", "value": "分析任务进入交付阶段"}],
                    "content": [{"value_type": "text", "value": "请按工作流路由继续处理该任务。"}],
                    "btn_list": [],
                },
            },
            {
                "id": "action_2",
                "type": "LarkMessageAction",
                "title": "忽略未完成任务",
                "next": None,
                "data": {
                    "receiver": [],
                    "send_to_everyone": False,
                    "title": [{"value_type": "text", "value": "任务暂不进入交付流程"}],
                    "content": [{"value_type": "text", "value": "状态未到已完成，暂不执行原生交付动作。"}],
                    "btn_list": [],
                },
            },
        ],
    }


def _role_body() -> dict[str, Any]:
    return {
        "role_name": "高管交付面",
        "role_type": "custom_role",
        "base_rule_map": {
            "copy": False,
            "download": False,
        },
        "table_rule_map": {
            "分析任务": {"perm": "read_only"},
            "综合报告": {"perm": "read_only"},
            "交付动作": {"perm": "read_only"},
        },
    }


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
