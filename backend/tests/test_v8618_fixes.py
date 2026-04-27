"""v8.6.18 — 验收 codex 报告里的两个真 bug 修复。"""
import json
import shlex
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.budget import record_usage


@pytest.mark.asyncio
async def test_record_usage_accepts_reasoning_tokens_keyword(monkeypatch):
    """v8.6.18：record_usage 新增 reasoning_tokens 维度，向后兼容。"""
    incr_calls: list[tuple[str, int]] = []

    async def fake_incr(key: str, value: int, ttl_seconds: int):
        incr_calls.append((key, value))
        return value

    monkeypatch.setattr("app.core.budget._incr", fake_incr)
    monkeypatch.setattr("app.core.budget.get_task_id", lambda: "t-x")
    monkeypatch.setattr("app.core.budget.get_tenant_id", lambda: "tenant-x")

    # 1) 老 caller 不传 reasoning_tokens — 不应有 :reasoning key
    incr_calls.clear()
    await record_usage(prompt_tokens=10, completion_tokens=20)
    assert all(":reasoning" not in k for k, _ in incr_calls)

    # 2) 新 caller 传 reasoning_tokens — 应有 :reasoning key
    incr_calls.clear()
    await record_usage(prompt_tokens=10, completion_tokens=20, reasoning_tokens=50)
    reasoning_keys = [k for k, _ in incr_calls if ":reasoning" in k]
    assert len(reasoning_keys) == 3, f"expected 3 reasoning keys (task/tenant/global), got {reasoning_keys}"
    # 推理 token 数应正确
    reasoning_values = [v for k, v in incr_calls if ":reasoning" in k]
    assert all(v == 50 for v in reasoning_values)


@pytest.mark.asyncio
async def test_record_usage_skips_reasoning_when_zero(monkeypatch):
    """reasoning_tokens=0 时不应写 :reasoning key（避免 noise）。"""
    incr_calls: list[tuple[str, int]] = []

    async def fake_incr(key: str, value: int, ttl_seconds: int):
        incr_calls.append((key, value))
        return value

    monkeypatch.setattr("app.core.budget._incr", fake_incr)
    monkeypatch.setattr("app.core.budget.get_task_id", lambda: "t-x")
    monkeypatch.setattr("app.core.budget.get_tenant_id", lambda: "tenant-x")

    incr_calls.clear()
    await record_usage(prompt_tokens=10, completion_tokens=20, reasoning_tokens=0)
    assert all(":reasoning" not in k for k, _ in incr_calls)


@pytest.mark.asyncio
async def test_setup_workflow_rolls_back_base_on_failure(monkeypatch):
    """v8.6.18：setup_workflow 任意阶段抛错应自动 DELETE base 回滚。"""
    from app.bitable_workflow import runner

    deleted: list[str] = []

    async def fake_create_bitable(name: str) -> dict:
        return {"app_token": "appfake", "url": "https://feishu.cn/base/appfake", "name": name}

    async def fake_create_table(app_token: str, table_name: str, fields: list[dict]) -> str:
        return "tbl_" + table_name

    async def fake_create_extra_views(*args, **kwargs):
        raise RuntimeError("simulated views failure (codex 注入)")

    async def fake_delete(app_token: str) -> None:
        deleted.append(app_token)

    monkeypatch.setattr(runner, "create_bitable", fake_create_bitable)
    monkeypatch.setattr(runner, "create_table", fake_create_table)
    monkeypatch.setattr(runner, "_create_extra_views", fake_create_extra_views)
    monkeypatch.setattr(runner, "_delete_base_best_effort", fake_delete)

    with pytest.raises(RuntimeError, match="simulated views failure"):
        await runner.setup_workflow(name="test-rollback")

    assert deleted == ["appfake"], "应当对失败的 base app_token 调一次 _delete_base_best_effort"


@pytest.mark.asyncio
async def test_setup_workflow_rolls_back_on_populate_failure(monkeypatch):
    """SEED 写入阶段失败也应回滚（codex 路径 D 残留 base 的真实场景）。"""
    from app.bitable_workflow import runner

    deleted: list[str] = []

    async def fake_create_bitable(name: str) -> dict:
        return {"app_token": "appB", "url": "u", "name": name}

    async def fake_create_table(app_token, table_name, fields):
        return "tbl_" + table_name

    async def fake_views(*args, **kwargs):
        return None

    async def fake_cleanup(*args, **kwargs):
        return None

    async def fake_populate(*args, **kwargs):
        raise RuntimeError("simulated SEED write 5xx")

    async def fake_delete(app_token: str) -> None:
        deleted.append(app_token)

    monkeypatch.setattr(runner, "create_bitable", fake_create_bitable)
    monkeypatch.setattr(runner, "create_table", fake_create_table)
    monkeypatch.setattr(runner, "_create_extra_views", fake_views)
    monkeypatch.setattr(runner, "_cleanup_auto_created_artifacts", fake_cleanup)
    monkeypatch.setattr(runner, "_populate_base_records", fake_populate)
    monkeypatch.setattr(runner, "_delete_base_best_effort", fake_delete)

    with pytest.raises(RuntimeError, match="simulated SEED write 5xx"):
        await runner.setup_workflow(name="test-populate-rollback")

    assert deleted == ["appB"]


def test_seed_csv_fence_uses_csv_language_marker():
    """v8.6.18 codex Top 5 #5：SEED 数据源围栏应带 csv 语言标记。"""
    from app.bitable_workflow import runner
    import inspect
    src = inspect.getsource(runner._populate_base_records)
    assert "```csv" in src, "SEED 围栏应带 ```csv 语言标记，便于 markdown 高亮 + parser 提示"


@pytest.mark.asyncio
async def test_setup_workflow_returns_native_assets_and_base_meta(monkeypatch):
    from app.bitable_workflow import runner

    async def fake_create_bitable(name: str) -> dict:
        return {"app_token": "appN", "url": "https://feishu.cn/base/appN", "name": name}

    async def fake_create_table(app_token: str, table_name: str, fields: list[dict]) -> str:
        return f"tbl_{table_name}"

    async def fake_create_views(*args, **kwargs):
        return {"views": [], "forms": [{"view_name": "📥 需求收集表", "view_id": "vew_form", "shared_url": "https://feishu.cn/form/abc"}]}

    async def fake_cleanup(*args, **kwargs):
        return None

    async def fake_populate(*args, **kwargs):
        return None

    monkeypatch.setattr(runner, "create_bitable", fake_create_bitable)
    monkeypatch.setattr(runner, "create_table", fake_create_table)
    monkeypatch.setattr(runner, "_create_extra_views", fake_create_views)
    monkeypatch.setattr(runner, "_cleanup_auto_created_artifacts", fake_cleanup)
    monkeypatch.setattr(runner, "_populate_base_records", fake_populate)

    result = await runner.setup_workflow(name="native-demo", mode="prod_empty", base_type="production")

    assert result["base_meta"]["mode"] == "prod_empty"
    assert result["base_meta"]["base_type"] == "production"
    assert result["native_assets"]["status"] == "blueprint_ready"
    assert result["native_assets"]["overall_state"] == "blueprint_ready"
    assert result["native_assets"]["form_blueprints"][0]["shared_url"] == "https://feishu.cn/form/abc"
    assert result["native_assets"]["form_blueprints"][0]["lifecycle_state"] == "created"
    assert result["native_assets"]["status_summary"]["counts"]["created"] == 1
    assert result["native_assets"]["status_summary"]["counts"]["blueprint_ready"] >= 1
    assert result["native_assets"]["manual_finish_checklist"][0]["done"] is True
    assert result["native_manifest"]["manifest_version"] == "v2"
    assert result["native_manifest"]["install_order"][0]["title"] == "启用高级权限"
    assert "lark-cli base +advperm-enable" in result["native_manifest"]["command_packs"][0]["commands"][0]
    assert any("+form-questions-create" in command for command in result["native_manifest"]["command_packs"][1]["commands"])
    assert any("A1 新任务入场提醒" in command for command in result["native_manifest"]["command_packs"][2]["commands"])
    assert any("高管交付面" in command for command in result["native_manifest"]["command_packs"][5]["commands"])


@pytest.mark.asyncio
async def test_apply_native_manifest_promotes_assets_to_created(monkeypatch):
    from app.bitable_workflow.native_installer import apply_native_manifest

    created_logs: list[dict] = []

    async def fake_cli_base(shortcut: str, *args: str):
        if shortcut == "+advperm-enable":
            return {"ok": True, "data": {"success": True}}
        if shortcut == "+form-create":
            return {"ok": True, "data": {"id": "vew_form_created"}}
        if shortcut == "+form-questions-create":
            return {"ok": True, "data": {"items": [{"id": "q_001", "title": "任务标题"}]}}
        if shortcut == "+workflow-create":
            return {"ok": True, "data": {"workflow_id": "wkf_auto_created"}}
        if shortcut == "+workflow-enable":
            return {"ok": True, "data": {"workflow_id": "wkf_auto_created", "status": "enabled"}}
        if shortcut == "+dashboard-create":
            return {"ok": True, "data": {"dashboard_id": "blk_auto_created"}}
        if shortcut == "+dashboard-block-create":
            return {"ok": True, "data": {"block": {"block_id": "cht_auto_created"}, "created": True}}
        if shortcut == "+dashboard-arrange":
            return {"ok": True, "data": {"dashboard_id": "blk_auto_created", "arranged": True}}
        if shortcut == "+role-create":
            return {"ok": True, "data": {"success": True}}
        raise AssertionError(f"unexpected shortcut {shortcut}")

    async def fake_create_record_optional_fields(_app_token, _table_id, fields, optional_keys=None):
        created_logs.append({"table_id": _table_id, "fields": fields, "optional_keys": optional_keys or []})
        return "rec_native_log"

    monkeypatch.setattr("app.bitable_workflow.native_installer.is_cli_available", lambda: True)
    monkeypatch.setattr("app.bitable_workflow.native_installer.cli_base", fake_cli_base)
    monkeypatch.setattr("app.bitable_workflow.native_installer.bitable_ops.create_record_optional_fields", fake_create_record_optional_fields)

    native_assets = {
        "form_blueprints": [{"name": "任务收集表单", "lifecycle_state": "manual_finish_required"}],
        "automation_templates": [{"name": "A1 新任务入场提醒", "lifecycle_state": "blueprint_ready"}],
        "workflow_blueprints": [{"name": "W1", "lifecycle_state": "blueprint_ready"}],
        "dashboard_blueprints": [{"name": "D1", "lifecycle_state": "blueprint_ready"}],
        "role_blueprints": [{"name": "R1", "lifecycle_state": "blueprint_ready"}],
        "manual_finish_checklist": [{}, {}, {"done": False}, {"done": False}, {"done": False}],
    }
    result = await apply_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task", "evidence": "tbl_evidence", "report": "tbl_report", "automation_log": "tbl_log"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets=native_assets,
        force=True,
    )

    assert result["native_assets"]["form_blueprints"][0]["lifecycle_state"] == "created"
    assert result["native_assets"]["form_blueprints"][0]["question_count"] >= 1
    assert result["native_assets"]["automation_templates"][0]["lifecycle_state"] == "created"
    assert result["native_assets"]["workflow_blueprints"][0]["lifecycle_state"] == "created"
    assert result["native_assets"]["dashboard_blueprints"][0]["lifecycle_state"] == "created"
    assert result["native_assets"]["role_blueprints"][0]["lifecycle_state"] == "created"
    assert result["native_assets"]["overall_state"] == "created"
    assert result["native_assets"]["manual_finish_checklist"][2]["done"] is True
    assert result["native_manifest"]["manifest_version"] == "v2"
    assert created_logs
    assert created_logs[0]["fields"]["触发来源"] == "native_manifest.apply"


@pytest.mark.asyncio
async def test_apply_native_manifest_marks_form_manual_when_form_id_missing(monkeypatch):
    from app.bitable_workflow.native_installer import apply_native_manifest

    async def fake_cli_base(shortcut: str, *args: str):
        if shortcut == "+form-create":
            return {"ok": True, "data": {}}
        if shortcut == "+workflow-create":
            return {"ok": True, "data": {"workflow_id": "wkf_auto_created"}}
        if shortcut == "+workflow-enable":
            return {"ok": True, "data": {"workflow_id": "wkf_auto_created", "status": "enabled"}}
        if shortcut == "+dashboard-create":
            return {"ok": True, "data": {"dashboard_id": "blk_auto_created"}}
        if shortcut == "+dashboard-block-create":
            return {"ok": True, "data": {"block": {"block_id": "cht_auto_created"}}}
        if shortcut == "+dashboard-arrange":
            return {"ok": True, "data": {"arranged": True}}
        if shortcut == "+advperm-enable":
            return {"ok": True, "data": {"success": True}}
        if shortcut == "+role-create":
            return {"ok": True, "data": {"success": True}}
        raise AssertionError(f"unexpected shortcut {shortcut}")

    async def fake_create_record_optional_fields(*args, **kwargs):
        return "rec_native_log"

    monkeypatch.setattr("app.bitable_workflow.native_installer.is_cli_available", lambda: True)
    monkeypatch.setattr("app.bitable_workflow.native_installer.cli_base", fake_cli_base)
    monkeypatch.setattr("app.bitable_workflow.native_installer.bitable_ops.create_record_optional_fields", fake_create_record_optional_fields)

    native_assets = {
        "form_blueprints": [{"name": "任务收集表单", "lifecycle_state": "manual_finish_required"}],
        "automation_templates": [],
        "workflow_blueprints": [],
        "dashboard_blueprints": [],
        "role_blueprints": [],
        "manual_finish_checklist": [{}, {}, {"done": False}, {"done": False}, {"done": False}],
    }
    result = await apply_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task", "automation_log": "tbl_log"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets=native_assets,
        surfaces=["form"],
        force=True,
    )

    form = result["native_assets"]["form_blueprints"][0]
    assert form["lifecycle_state"] == "manual_finish_required"
    assert form["cloud_object_id"] == ""
    assert "缺少 form_id" in form["blocking_reason"]
    assert result["report"][0]["status"] == "manual_finish_required"


@pytest.mark.asyncio
async def test_scheduler_merge_template_defaults_keeps_open_ids(monkeypatch):
    from app.bitable_workflow import scheduler
    from app.agents.base_agent import AgentResult

    async def fake_list_records(app_token: str, table_id: str, max_records: int = 200):
        return [
            {
                "fields": {
                    "启用": True,
                    "模板名称": "等待拍板默认模板",
                    "适用工作流路由": "等待拍板",
                    "适用输出目的": "管理决策",
                    "默认汇报对象": "CEO/管理层",
                    "默认汇报对象OpenID": "ou_report",
                    "默认拍板负责人": "CEO/管理层",
                    "默认拍板负责人OpenID": "ou_approve",
                    "默认执行负责人": "执行负责人A",
                    "默认执行负责人OpenID": "ou_execute",
                    "默认复核负责人": "复核负责人A",
                    "默认复核负责人OpenID": "ou_review",
                    "默认复盘负责人": "复盘负责人A",
                    "默认复盘负责人OpenID": "ou_retro",
                    "默认复核SLA小时": 24,
                }
            }
        ]

    monkeypatch.setattr("app.bitable_workflow.scheduler.bitable_ops.list_records", fake_list_records)

    merged = await scheduler._apply_template_config(
        app_token="app_token",
        template_tid="tbl_template",
        task_title="审计任务",
        task_fields={"输出目的": "管理决策", "套用模板": "等待拍板默认模板"},
        review_fields=None,
        ceo_result=AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[],
            action_items=[],
            raw_output="",
        ),
        payload={"工作流路由": "等待拍板"},
    )

    assert merged["汇报对象OpenID"] == "ou_report"
    assert merged["拍板负责人OpenID"] == "ou_approve"
    assert merged["执行负责人OpenID"] == "ou_execute"
    assert merged["复核负责人OpenID"] == "ou_review"
    assert merged["复盘负责人OpenID"] == "ou_retro"


def test_native_manifest_commands_shell_quote_json_and_text():
    from app.bitable_workflow.native_manifest import (
        _form_commands,
        _role_commands,
        _workflow_create_commands,
    )

    workflow_commands = _workflow_create_commands(
        "app token",
        [
            {
                "name": "W1 审计路由",
                "body": {
                    "title": "O'Hara 路由",
                    "steps": [{"name": "汇报给 CEO's Office"}],
                },
            }
        ],
    )
    workflow_parts = shlex.split(workflow_commands[1])
    workflow_json = workflow_parts[workflow_parts.index("--json") + 1]
    assert json.loads(workflow_json)["title"] == "O'Hara 路由"

    form_commands = _form_commands(
        "app token",
        "tbl task",
        {
            "name": "任务收集表单 O'Hara",
            "description": "给 CEO's Office 的闭环入口",
            "questions": [{"title": "谁的 \"问题\"?", "type": "text"}],
        },
    )
    form_create_parts = shlex.split(form_commands[0])
    assert form_create_parts[form_create_parts.index("--name") + 1] == "任务收集表单 O'Hara"
    assert form_create_parts[form_create_parts.index("--description") + 1] == "给 CEO's Office 的闭环入口"
    form_question_parts = shlex.split(form_commands[2])
    form_questions_json = form_question_parts[form_question_parts.index("--questions") + 1]
    assert json.loads(form_questions_json)[0]["title"] == "谁的 \"问题\"?"

    role_commands = _role_commands(
        "app token",
        [{"name": "高管's Role", "config": {"role_name": "高管's Role", "desc": "CEO's scope"}}],
    )
    role_parts = shlex.split(role_commands[1])
    role_json = role_parts[role_parts.index("--json") + 1]
    assert json.loads(role_json)["desc"] == "CEO's scope"


def test_native_manifest_command_pack_status_tracks_native_assets():
    from app.bitable_workflow.native_manifest import build_native_manifest

    manifest = build_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets={
            "form_blueprints": [{"lifecycle_state": "created"}],
            "automation_templates": [{"lifecycle_state": "manual_finish_required"}],
            "workflow_blueprints": [{"lifecycle_state": "created"}, {"lifecycle_state": "blueprint_ready"}],
            "dashboard_blueprints": [{"lifecycle_state": "permission_blocked"}],
            "role_blueprints": [{"lifecycle_state": "created"}],
        },
    )

    by_key = {pack["key"]: pack["status"] for pack in manifest["command_packs"]}
    assert by_key["form"] == "created"
    assert by_key["automation"] == "manual_finish_required"
    assert by_key["workflow"] == "blueprint_ready"
    assert by_key["dashboard"] == "permission_blocked"
    assert by_key["role"] == "created"
    assert by_key["advperm"] == "created"


def test_native_manifest_advperm_status_is_independent_from_role_status():
    from app.bitable_workflow.native_manifest import build_native_manifest

    manifest = build_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets={
            "advperm_state": "created",
            "form_blueprints": [],
            "automation_templates": [],
            "workflow_blueprints": [],
            "dashboard_blueprints": [],
            "role_blueprints": [{"lifecycle_state": "manual_finish_required"}],
        },
    )

    by_key = {pack["key"]: pack["status"] for pack in manifest["command_packs"]}
    assert by_key["advperm"] == "created"
    assert by_key["role"] == "manual_finish_required"


@pytest.mark.asyncio
async def test_apply_native_manifest_refreshes_checklist_states_and_done(monkeypatch):
    from app.bitable_workflow.native_installer import apply_native_manifest

    async def fake_cli_base(shortcut: str, *args: str):
        if shortcut == "+advperm-enable":
            return {"ok": True, "data": {"success": True}}
        if shortcut == "+workflow-create":
            return {"ok": True, "data": {"workflow_id": "wkf_created"}}
        if shortcut == "+workflow-enable":
            return {"ok": True, "data": {"workflow_id": "wkf_created", "status": "enabled"}}
        if shortcut == "+dashboard-create":
            return {"ok": True, "data": {"dashboard_id": "dsh_created"}}
        if shortcut == "+dashboard-block-create":
            return {"ok": True, "data": {"block": {"block_id": "blk_created"}}}
        if shortcut == "+dashboard-arrange":
            return {"ok": True, "data": {"arranged": True}}
        if shortcut == "+role-create":
            return {"ok": True, "data": {"success": True}}
        raise AssertionError(f"unexpected shortcut {shortcut}")

    async def fake_create_record_optional_fields(*args, **kwargs):
        return "rec_native_log"

    monkeypatch.setattr("app.bitable_workflow.native_installer.is_cli_available", lambda: True)
    monkeypatch.setattr("app.bitable_workflow.native_installer.cli_base", fake_cli_base)
    monkeypatch.setattr("app.bitable_workflow.native_installer.bitable_ops.create_record_optional_fields", fake_create_record_optional_fields)

    native_assets = {
        "form_blueprints": [{"name": "任务收集表单", "lifecycle_state": "manual_finish_required", "shared_url": ""}],
        "automation_templates": [{"name": "A1", "lifecycle_state": "blueprint_ready"}],
        "workflow_blueprints": [{"name": "W1", "lifecycle_state": "blueprint_ready"}],
        "dashboard_blueprints": [{"name": "D1", "lifecycle_state": "blueprint_ready"}],
        "role_blueprints": [{"name": "R1", "lifecycle_state": "blueprint_ready"}],
        "manual_finish_checklist": [
            {"name": "开放任务收集表单", "state": "manual_finish_required", "done": False},
            {"name": "配置主表自动化模板", "state": "blueprint_ready", "done": False},
            {"name": "创建路由工作流", "state": "blueprint_ready", "done": False},
            {"name": "搭建管理仪表盘", "state": "blueprint_ready", "done": False},
            {"name": "按角色配置高级权限", "state": "blueprint_ready", "done": False},
        ],
    }
    result = await apply_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task", "automation_log": "tbl_log"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets=native_assets,
        surfaces=["automation", "workflow", "dashboard", "role"],
        force=True,
    )

    checklist = result["native_assets"]["manual_finish_checklist"]
    assert checklist[0]["state"] == "manual_finish_required"
    assert checklist[0]["done"] is False
    assert checklist[1]["state"] == "created"
    assert checklist[1]["done"] is True
    assert checklist[2]["state"] == "created"
    assert checklist[2]["done"] is True
    assert checklist[3]["state"] == "created"
    assert checklist[3]["done"] is True
    assert checklist[4]["state"] == "created"
    assert checklist[4]["done"] is True


@pytest.mark.asyncio
async def test_apply_native_manifest_marks_dashboard_manual_when_blocks_partial(monkeypatch):
    from app.bitable_workflow.native_installer import apply_native_manifest

    block_call_count = 0

    async def fake_cli_base(shortcut: str, *args: str):
        nonlocal block_call_count
        if shortcut == "+dashboard-create":
            return {"ok": True, "data": {"dashboard_id": "dsh_created"}}
        if shortcut == "+dashboard-block-create":
            block_call_count += 1
            if block_call_count == 1:
                return {"ok": True, "data": {"block": {"block_id": "blk_001"}}}
            return {"ok": True, "data": {"block": {}}}
        if shortcut == "+dashboard-arrange":
            return {"ok": True, "data": {"arranged": True}}
        raise AssertionError(f"unexpected shortcut {shortcut}")

    async def fake_create_record_optional_fields(*args, **kwargs):
        return "rec_native_log"

    monkeypatch.setattr("app.bitable_workflow.native_installer.is_cli_available", lambda: True)
    monkeypatch.setattr("app.bitable_workflow.native_installer.cli_base", fake_cli_base)
    monkeypatch.setattr("app.bitable_workflow.native_installer.bitable_ops.create_record_optional_fields", fake_create_record_optional_fields)

    native_assets = {
        "form_blueprints": [],
        "automation_templates": [],
        "workflow_blueprints": [],
        "dashboard_blueprints": [{"name": "D1", "lifecycle_state": "blueprint_ready"}],
        "role_blueprints": [],
        "manual_finish_checklist": [],
    }
    result = await apply_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task", "automation_log": "tbl_log"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets=native_assets,
        surfaces=["dashboard"],
        force=True,
    )

    dashboard = result["native_assets"]["dashboard_blueprints"][0]
    assert dashboard["lifecycle_state"] == "manual_finish_required"
    assert dashboard["cloud_object_id"] == "dsh_created"
    assert dashboard["cloud_block_count"] == 1
    assert "block 创建不完整" in dashboard["blocking_reason"]
    assert result["report"][0]["status"] == "manual_finish_required"
    assert result["report"][0]["expected_block_count"] > result["report"][0]["block_count"]


@pytest.mark.asyncio
async def test_apply_native_manifest_requires_success_true_for_advperm_and_role(monkeypatch):
    from app.bitable_workflow.native_installer import apply_native_manifest

    async def fake_cli_base(shortcut: str, *args: str):
        if shortcut == "+advperm-enable":
            return {"ok": True, "data": {"success": False}}
        if shortcut == "+role-create":
            return {"ok": True, "data": {"success": False}}
        raise AssertionError(f"unexpected shortcut {shortcut}")

    async def fake_create_record_optional_fields(*args, **kwargs):
        return "rec_native_log"

    monkeypatch.setattr("app.bitable_workflow.native_installer.is_cli_available", lambda: True)
    monkeypatch.setattr("app.bitable_workflow.native_installer.cli_base", fake_cli_base)
    monkeypatch.setattr("app.bitable_workflow.native_installer.bitable_ops.create_record_optional_fields", fake_create_record_optional_fields)

    native_assets = {
        "form_blueprints": [],
        "automation_templates": [],
        "workflow_blueprints": [],
        "dashboard_blueprints": [],
        "role_blueprints": [{"name": "R1", "lifecycle_state": "blueprint_ready"}],
        "manual_finish_checklist": [],
    }
    result = await apply_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task", "automation_log": "tbl_log"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets=native_assets,
        surfaces=["role"],
        force=True,
    )

    assert result["report"][0]["name"] == "启用高级权限"
    assert result["report"][0]["status"] == "manual_finish_required"
    assert result["native_assets"]["advperm_state"] == "manual_finish_required"
    assert result["native_assets"]["role_blueprints"][0]["lifecycle_state"] == "manual_finish_required"
    assert "success=true" in result["native_assets"]["role_blueprints"][0]["blocking_reason"]


@pytest.mark.asyncio
async def test_apply_native_manifest_marks_workflow_manual_when_enable_not_confirmed(monkeypatch):
    from app.bitable_workflow.native_installer import apply_native_manifest

    async def fake_cli_base(shortcut: str, *args: str):
        if shortcut == "+workflow-create":
            return {"ok": True, "data": {"workflow_id": "wkf_created"}}
        if shortcut == "+workflow-enable":
            return {"ok": True, "data": {"workflow_id": "wkf_created", "status": "disabled"}}
        raise AssertionError(f"unexpected shortcut {shortcut}")

    async def fake_create_record_optional_fields(*args, **kwargs):
        return "rec_native_log"

    monkeypatch.setattr("app.bitable_workflow.native_installer.is_cli_available", lambda: True)
    monkeypatch.setattr("app.bitable_workflow.native_installer.cli_base", fake_cli_base)
    monkeypatch.setattr("app.bitable_workflow.native_installer.bitable_ops.create_record_optional_fields", fake_create_record_optional_fields)

    native_assets = {
        "form_blueprints": [],
        "automation_templates": [],
        "workflow_blueprints": [{"name": "W1", "lifecycle_state": "blueprint_ready"}],
        "dashboard_blueprints": [],
        "role_blueprints": [],
        "manual_finish_checklist": [],
    }
    result = await apply_native_manifest(
        app_token="app_token",
        base_url="https://feishu.cn/base/app_token",
        table_ids={"task": "tbl_task", "automation_log": "tbl_log"},
        base_meta={"base_type": "production", "mode": "prod_empty", "schema_version": "v-test"},
        native_assets=native_assets,
        surfaces=["workflow"],
        force=True,
    )

    workflow = result["native_assets"]["workflow_blueprints"][0]
    assert workflow["lifecycle_state"] == "manual_finish_required"
    assert workflow["cloud_object_id"] == "wkf_created"
    assert "status=enabled" in workflow["blocking_reason"]
    assert result["report"][0]["status"] == "manual_finish_required"


@pytest.mark.asyncio
async def test_workflow_setup_keeps_base_result_when_native_apply_fails(monkeypatch):
    from app.api import workflow

    async def fake_setup_workflow(name: str, mode: str, base_type: str):
        return {
            "app_token": "app_token",
            "url": "https://feishu.cn/base/app_token",
            "table_ids": {"task": "tbl_task"},
            "base_meta": {"base_type": base_type, "mode": mode, "schema_version": "v-test"},
            "native_assets": {"status": "blueprint_ready"},
            "native_manifest": {"manifest_version": "v2"},
        }

    async def fake_apply_native_manifest(**kwargs):
        raise RuntimeError("lark-cli unavailable")

    audit_calls: list[dict] = []

    async def fake_record_audit(name: str, target: str, payload: dict):
        audit_calls.append({"name": name, "target": target, "payload": payload})

    monkeypatch.setattr("app.api.workflow.runner.is_running", lambda: False)
    monkeypatch.setattr("app.api.workflow.runner.setup_workflow", fake_setup_workflow)
    monkeypatch.setattr("app.api.workflow.apply_native_manifest", fake_apply_native_manifest)
    monkeypatch.setattr("app.api.workflow.record_audit", fake_record_audit)
    workflow._state.clear()

    result = await workflow.workflow_setup(
        workflow.SetupRequest(name="审计 base", mode="prod_empty", base_type="production", apply_native=True)
    )

    assert result["app_token"] == "app_token"
    assert result["url"] == "https://feishu.cn/base/app_token"
    assert result["native_manifest"]["manifest_version"] == "v2"
    assert result["native_apply_report"][0]["status"] == "manual_finish_required"
    assert "lark-cli unavailable" in result["native_apply_report"][0]["error"]
    assert workflow._state["app_token"] == "app_token"
    assert audit_calls[0]["name"] == "workflow.setup"


@pytest.mark.asyncio
async def test_write_native_install_logs_maps_manual_finish_to_pending_completion(monkeypatch):
    from app.bitable_workflow import native_installer

    written: list[dict] = []

    async def fake_create_record_optional_fields(app_token, table_id, fields, optional_keys=None):
        written.append({"app_token": app_token, "table_id": table_id, "fields": fields, "optional_keys": optional_keys or []})
        return "rec_log"

    monkeypatch.setattr(native_installer.bitable_ops, "create_record_optional_fields", fake_create_record_optional_fields)

    await native_installer._write_native_install_logs(
        app_token="app_token",
        automation_log_tid="tbl_log",
        report=[
            {"surface": "form", "name": "任务收集表单", "status": "manual_finish_required", "error": "缺少共享链接"},
            {"surface": "role", "name": "高级权限", "status": "permission_blocked", "error": "permission denied"},
        ],
        base_meta={"base_type": "production", "mode": "prod_empty"},
        applied_at=123456,
    )

    assert written[0]["fields"]["执行状态"] == "待补完"
    assert written[1]["fields"]["执行状态"] == "执行失败"


def test_native_role_field_rules_cover_all_non_system_fields():
    from app.bitable_workflow import schema as workflow_schema
    from app.bitable_workflow.native_specs import (
        _execution_action_field_rule,
        _execution_archive_field_rule,
        _execution_task_field_rule,
        _review_history_field_rule,
        _review_result_field_rule,
        _review_task_field_rule,
    )

    def expected_fields(fields: list[dict]) -> set[str]:
        excluded_types = {
            workflow_schema.CREATED_TIME_FIELD_TYPE,
            workflow_schema.MODIFIED_TIME_FIELD_TYPE,
            workflow_schema.AUTO_NUMBER_FIELD_TYPE,
        }
        return {
            str(field["field_name"])
            for field in fields
            if str(field.get("field_name") or "").strip() and field.get("type") not in excluded_types
        }

    task_expected = expected_fields(workflow_schema.TASK_FIELDS)
    assert set(_execution_task_field_rule()["field_perms"].keys()) == task_expected
    assert set(_review_task_field_rule()["field_perms"].keys()) == task_expected

    action_expected = expected_fields(workflow_schema.ACTION_FIELDS)
    assert set(_execution_action_field_rule()["field_perms"].keys()) == action_expected

    archive_expected = expected_fields(workflow_schema.DELIVERY_ARCHIVE_FIELDS)
    assert set(_execution_archive_field_rule()["field_perms"].keys()) == archive_expected

    review_expected = expected_fields(workflow_schema.REVIEW_FIELDS)
    assert set(_review_result_field_rule()["field_perms"].keys()) == review_expected

    review_history_expected = expected_fields(workflow_schema.REVIEW_HISTORY_FIELDS)
    assert set(_review_history_field_rule()["field_perms"].keys()) == review_history_expected
