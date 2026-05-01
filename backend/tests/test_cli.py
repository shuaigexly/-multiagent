"""v8.6.20-r47: CLI 工具回归。

锁定 14 个子命令的 argparse 装配 + 关键命令的 HTTP 调用契约：
- 路径 / method / params / body 都对端点合同
- 出错时 exit code != 0
- export 命令支持 --out 写文件
"""
from __future__ import annotations

import json

import httpx
import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    monkeypatch.setenv("PUFF_C21_API_BASE", "http://test-host:9999")
    monkeypatch.setenv("PUFF_C21_API_KEY", "test-key-xyz")
    yield


def _stub_http(monkeypatch, *, expected_method, expected_path, response_payload, response_status=200):
    """安装一个 httpx.request mock，校验 method+path 匹配 + 返预设 payload。"""
    captured = {}

    def fake_request(method, url, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers", {})
        assert method == expected_method, f"{method} != {expected_method}"
        assert expected_path in url, f"{expected_path} not in {url}"
        # 构造一个轻量 Response 对象
        return httpx.Response(
            status_code=response_status,
            content=json.dumps(response_payload).encode("utf-8"),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr("httpx.request", fake_request)
    return captured


def test_cli_parser_lists_all_subcommands():
    from app.cli import build_parser

    parser = build_parser()
    sub = parser._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert {
        "preflight", "setup", "start", "stop", "status", "telemetry",
        "agents", "agent-profile", "similar", "cancel", "replay",
        "export", "audit", "seed",
    } <= set(sub.keys())


def test_cli_preflight_calls_get(monkeypatch, capsys):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="GET", expected_path="/api/v1/workflow/preflight",
        response_payload={"ok": True, "checks": []},
    )

    rc = main(["preflight"])
    assert rc == 0
    assert captured["method"] == "GET"
    # API key header 透传
    assert captured["headers"]["X-API-Key"] == "test-key-xyz"
    out = capsys.readouterr().out
    assert "ok" in out


def test_cli_telemetry_returns_zero_on_success(monkeypatch, capsys):
    from app.cli import main

    _stub_http(
        monkeypatch, expected_method="GET", expected_path="/api/v1/workflow/telemetry",
        response_payload={"workflow": {"running": False}, "budget": {}},
    )
    rc = main(["telemetry"])
    assert rc == 0


def test_cli_seed_posts_body_and_force_flag(monkeypatch):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="POST", expected_path="/api/v1/workflow/seed",
        response_payload={"record_id": "rec_new"},
    )
    rc = main([
        "seed",
        "--app-token", "app",
        "--table-id", "tbl",
        "--title", "Q3 复盘",
        "--dimension", "数据复盘",
        "--background", "GMV 下滑",
        "--force",
    ])
    assert rc == 0
    assert captured["json"]["title"] == "Q3 复盘"
    assert captured["json"]["dimension"] == "数据复盘"
    assert captured["params"] == {"force": "true"}


def test_cli_cancel_uses_path_record_id(monkeypatch):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="POST", expected_path="/api/v1/workflow/cancel/rec_xx",
        response_payload={"cancelled": True},
    )
    rc = main(["cancel", "--record-id", "rec_xx", "--app-token", "app_a"])
    assert rc == 0
    assert "rec_xx" in captured["url"]
    assert captured["params"] == {"app_token": "app_a"}


def test_cli_replay_passes_fresh_flag(monkeypatch):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="POST", expected_path="/api/v1/workflow/replay/rec_re",
        response_payload={"replayed": True},
    )
    rc = main(["replay", "--record-id", "rec_re", "--app-token", "app", "--fresh"])
    assert rc == 0
    assert captured["params"]["fresh"] == "true"


def test_cli_similar_passes_query_params(monkeypatch):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="GET", expected_path="/api/v1/workflow/similar",
        response_payload={"count": 0, "matches": []},
    )
    rc = main([
        "similar",
        "--title", "Q4 复盘",
        "--dimension", "数据复盘",
        "--limit", "5",
    ])
    assert rc == 0
    p = captured["params"]
    assert p["title"] == "Q4 复盘"
    assert p["dimension"] == "数据复盘"
    assert p["limit"] == 5


def test_cli_audit_filter_target_and_prefix(monkeypatch):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="GET", expected_path="/api/v1/workflow/audit",
        response_payload={"count": 0, "events": []},
    )
    rc = main([
        "audit",
        "--target", "rec_xxx",
        "--action-prefix", "workflow.",
        "--limit", "100",
    ])
    assert rc == 0
    assert captured["params"]["target"] == "rec_xxx"
    assert captured["params"]["action_prefix"] == "workflow."
    assert captured["params"]["limit"] == 100


def test_cli_agent_profile_uses_path_id(monkeypatch):
    from app.cli import main

    captured = _stub_http(
        monkeypatch, expected_method="GET",
        expected_path="/api/v1/workflow/agents/data_analyst/profile",
        response_payload={"id": "data_analyst"},
    )
    rc = main(["agent-profile", "data_analyst"])
    assert rc == 0
    assert "data_analyst/profile" in captured["url"]


def test_cli_export_writes_to_file(monkeypatch, tmp_path):
    from app.cli import main

    out_file = tmp_path / "report.md"

    def fake_get(url, **kwargs):
        return httpx.Response(
            status_code=200,
            content="# 测试报告\n\nOK".encode("utf-8"),
            headers={"content-type": "text/markdown"},
        )

    monkeypatch.setattr("httpx.get", fake_get)
    rc = main(["export", "--record-id", "rec_ex", "--out", str(out_file)])
    assert rc == 0
    assert out_file.exists()
    assert "测试报告" in out_file.read_text(encoding="utf-8")


def test_cli_returns_1_on_http_4xx(monkeypatch):
    from app.cli import main

    _stub_http(
        monkeypatch, expected_method="GET", expected_path="/api/v1/workflow/preflight",
        response_payload={"detail": "unauthorized"},
        response_status=401,
    )
    rc = main(["preflight"])
    assert rc == 1


def test_cli_returns_2_on_network_error(monkeypatch):
    from app.cli import main

    def explode(*_a, **_kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.request", explode)
    rc = main(["preflight"])
    assert rc == 2
