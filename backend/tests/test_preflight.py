"""v8.6.20-r37: 部署前置体检 (/preflight) 回归。

覆盖：
1. 4 个 check 并发跑，全部成功 → ok=True
2. 任一 check 失败 → ok=False，但其他 check 仍正常返回
3. 国内模型合规：openai.com / anthropic.com 等被黑名单识别
4. Redis 未配置时 ok=True（单实例合规）
5. /preflight 端点 wraps run_preflight 并 dict-ify 输出
"""
from __future__ import annotations

from types import ModuleType
import sys

import pytest


def _ensure_sse_stub(monkeypatch):
    sse_pkg = ModuleType("sse_starlette")
    sse_mod = ModuleType("sse_starlette.sse")
    sse_mod.EventSourceResponse = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sse_starlette", sse_pkg)
    monkeypatch.setitem(sys.modules, "sse_starlette.sse", sse_mod)


@pytest.mark.asyncio
async def test_run_preflight_all_checks_pass(monkeypatch):
    from app.bitable_workflow import preflight

    async def fake_token():
        return "t-abc123def456"

    async def fake_call_llm(*_a, **_kw):
        return "1"

    monkeypatch.setattr("app.feishu.aily.get_tenant_access_token", fake_token)
    monkeypatch.setattr("app.core.llm_client.call_llm", fake_call_llm)
    monkeypatch.setattr("app.core.settings.get_llm_base_url", lambda: "https://api.deepseek.com/v1")
    monkeypatch.delenv("REDIS_URL", raising=False)

    report = await preflight.run_preflight()
    assert report.ok is True, [(c.name, c.ok, c.detail) for c in report.checks]
    assert len(report.checks) == 4
    by_name = {c.name: c for c in report.checks}
    assert by_name["feishu_token"].ok
    assert by_name["llm"].ok
    assert by_name["llm_compliance"].ok
    assert by_name["redis"].ok


@pytest.mark.asyncio
async def test_run_preflight_flags_overseas_llm_base_url(monkeypatch):
    from app.bitable_workflow import preflight

    async def fake_token():
        return "t-abc"

    async def fake_call_llm(*_a, **_kw):
        return "1"

    monkeypatch.setattr("app.feishu.aily.get_tenant_access_token", fake_token)
    monkeypatch.setattr("app.core.llm_client.call_llm", fake_call_llm)
    monkeypatch.setattr("app.core.settings.get_llm_base_url", lambda: "https://api.openai.com/v1")
    monkeypatch.delenv("REDIS_URL", raising=False)

    report = await preflight.run_preflight()
    assert report.ok is False
    by_name = {c.name: c for c in report.checks}
    assert by_name["llm_compliance"].ok is False
    assert "openai.com" in by_name["llm_compliance"].detail
    # 其他 check 不受影响
    assert by_name["feishu_token"].ok
    assert by_name["llm"].ok


@pytest.mark.asyncio
async def test_run_preflight_one_failure_does_not_block_others(monkeypatch):
    from app.bitable_workflow import preflight

    async def fake_token():
        raise RuntimeError("invalid app_id")

    async def fake_call_llm(*_a, **_kw):
        return "1"

    monkeypatch.setattr("app.feishu.aily.get_tenant_access_token", fake_token)
    monkeypatch.setattr("app.core.llm_client.call_llm", fake_call_llm)
    monkeypatch.setattr("app.core.settings.get_llm_base_url", lambda: "https://api.deepseek.com/v1")
    monkeypatch.delenv("REDIS_URL", raising=False)

    report = await preflight.run_preflight()
    assert report.ok is False
    by_name = {c.name: c for c in report.checks}
    assert by_name["feishu_token"].ok is False
    assert "invalid app_id" in by_name["feishu_token"].detail
    assert by_name["feishu_token"].advisory  # 必须给修复建议
    assert by_name["llm"].ok is True  # 互不阻塞
    assert by_name["llm_compliance"].ok is True
    assert by_name["redis"].ok is True


@pytest.mark.asyncio
async def test_run_preflight_redis_not_configured_is_ok(monkeypatch):
    from app.bitable_workflow import preflight

    async def fake_token():
        return "t-abc"

    async def fake_call_llm(*_a, **_kw):
        return "1"

    monkeypatch.setattr("app.feishu.aily.get_tenant_access_token", fake_token)
    monkeypatch.setattr("app.core.llm_client.call_llm", fake_call_llm)
    monkeypatch.setattr("app.core.settings.get_llm_base_url", lambda: "https://api.deepseek.com/v1")
    monkeypatch.delenv("REDIS_URL", raising=False)

    report = await preflight.run_preflight()
    redis_check = next(c for c in report.checks if c.name == "redis")
    assert redis_check.ok is True
    # detail 里要明示是单实例合规，不是 Redis 真的连上了
    assert "未配置" in redis_check.detail or "单实例" in redis_check.detail


def test_report_to_dict_serializes_all_fields():
    from app.bitable_workflow import preflight
    from app.bitable_workflow.preflight import PreflightCheck, PreflightReport

    report = PreflightReport(
        ok=False,
        started_at="2026-04-30T00:00:00+00:00",
        elapsed_ms=1234,
        checks=[
            PreflightCheck(
                name="x", label="X check", ok=False,
                detail="something failed", advisory="fix this", elapsed_ms=500,
            ),
        ],
    )
    out = preflight.report_to_dict(report)
    assert out["ok"] is False
    assert out["elapsed_ms"] == 1234
    assert len(out["checks"]) == 1
    c = out["checks"][0]
    assert c["name"] == "x"
    assert c["label"] == "X check"
    assert c["ok"] is False
    assert c["detail"] == "something failed"
    assert c["advisory"] == "fix this"
    assert c["elapsed_ms"] == 500


@pytest.mark.asyncio
async def test_preflight_endpoint_returns_dict_payload(monkeypatch):
    _ensure_sse_stub(monkeypatch)
    from app.api import workflow
    from app.bitable_workflow import preflight as pf_module
    from app.bitable_workflow.preflight import PreflightCheck, PreflightReport

    async def fake_run():
        return PreflightReport(
            ok=True,
            started_at="2026-05-01T00:00:00+00:00",
            elapsed_ms=200,
            checks=[
                PreflightCheck(name="feishu_token", label="飞书", ok=True, detail="ok", elapsed_ms=50),
                PreflightCheck(name="llm", label="LLM", ok=True, detail="ok", elapsed_ms=100),
                PreflightCheck(name="llm_compliance", label="合规", ok=True, detail="ok", elapsed_ms=10),
                PreflightCheck(name="redis", label="Redis", ok=True, detail="单实例 OK", elapsed_ms=2),
            ],
        )

    monkeypatch.setattr(pf_module, "run_preflight", fake_run)

    payload = await workflow.workflow_preflight()
    assert payload["ok"] is True
    assert payload["elapsed_ms"] == 200
    assert len(payload["checks"]) == 4
    assert payload["checks"][0]["name"] == "feishu_token"
