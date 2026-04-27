"""v8.6.18 — 验收 codex 报告里的两个真 bug 修复。"""
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
