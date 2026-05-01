"""Headless CLI 工具（v8.6.20-r47） — `python -m app.cli <command>`。

用途
====
让评审 / 运维 / CI 不依赖前端 / Swagger UI 也能驱动整套 workflow API。
所有命令共享一个 HTTP client，统一从环境变量取 base URL 和 API key。

使用
====
    export PUFF_C21_API_BASE=http://localhost:8000
    export PUFF_C21_API_KEY=your-api-key

    python -m app.cli preflight
    python -m app.cli setup --name "demo"
    python -m app.cli start --app-token APP --task-table TBL
    python -m app.cli telemetry
    python -m app.cli agents
    python -m app.cli agent-profile data_analyst
    python -m app.cli similar --title "Q3 经营复盘" --limit 3
    python -m app.cli cancel --record-id rec_xxx --app-token APP
    python -m app.cli replay --record-id rec_xxx --app-token APP --fresh
    python -m app.cli export --record-id rec_xxx --out report.md
    python -m app.cli audit --target rec_xxx
    python -m app.cli status [--app-token APP]
    python -m app.cli stop

退出码
======
    0  成功
    1  HTTP 4xx/5xx（业务错误）
    2  网络错误 / 配置缺失
    3  本地参数错误（argparse 已处理）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.stderr.write("ERROR: httpx not installed. Run: pip install httpx\n")
    sys.exit(2)


# ---- 配置 ----


def _api_base() -> str:
    return os.getenv("PUFF_C21_API_BASE", "http://localhost:8000").rstrip("/")


def _api_key() -> str:
    key = os.getenv("PUFF_C21_API_KEY", "").strip()
    if not key:
        sys.stderr.write(
            "WARNING: PUFF_C21_API_KEY not set; if backend has API_KEY required, calls will 401.\n"
        )
    return key


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    key = _api_key()
    if key:
        h["X-API-Key"] = key
    return h


# ---- HTTP helpers ----


def _print_response(resp: httpx.Response, *, raw: bool = False) -> int:
    if raw:
        sys.stdout.write(resp.text)
        if not resp.text.endswith("\n"):
            sys.stdout.write("\n")
    else:
        try:
            print(json.dumps(resp.json(), ensure_ascii=False, indent=2))
        except json.JSONDecodeError:
            sys.stdout.write(resp.text + "\n")
    return 0 if resp.status_code < 400 else 1


def _request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    raw_response: bool = False,
) -> int:
    url = f"{_api_base()}{path}"
    try:
        resp = httpx.request(
            method,
            url,
            headers=_headers(),
            params=params,
            json=json_body,
            timeout=60.0,
        )
    except httpx.RequestError as exc:
        sys.stderr.write(f"NETWORK ERROR: {exc}\n")
        return 2

    return _print_response(resp, raw=raw_response)


# ---- 子命令 handlers ----


def _cmd_preflight(_args) -> int:
    return _request("GET", "/api/v1/workflow/preflight")


def _cmd_setup(args) -> int:
    body = {"name": args.name, "mode": args.mode, "base_type": args.base_type, "apply_native": args.apply_native}
    return _request("POST", "/api/v1/workflow/setup", json_body=body)


def _cmd_start(args) -> int:
    body = {
        "app_token": args.app_token,
        "table_ids": json.loads(args.table_ids) if isinstance(args.table_ids, str) else args.table_ids,
        "interval": args.interval,
        "analysis_every": args.analysis_every,
    }
    return _request("POST", "/api/v1/workflow/start", json_body=body)


def _cmd_stop(_args) -> int:
    return _request("POST", "/api/v1/workflow/stop")


def _cmd_status(args) -> int:
    params = {"app_token": args.app_token} if args.app_token else None
    return _request("GET", "/api/v1/workflow/status", params=params)


def _cmd_telemetry(_args) -> int:
    return _request("GET", "/api/v1/workflow/telemetry")


def _cmd_agents(_args) -> int:
    return _request("GET", "/api/v1/workflow/agents")


def _cmd_agent_profile(args) -> int:
    return _request("GET", f"/api/v1/workflow/agents/{args.agent_id}/profile")


def _cmd_similar(args) -> int:
    params = {"title": args.title, "dimension": args.dimension or "", "background": args.background or "", "limit": args.limit}
    if args.app_token:
        params["app_token"] = args.app_token
    return _request("GET", "/api/v1/workflow/similar", params=params)


def _cmd_cancel(args) -> int:
    params = {"app_token": args.app_token} if args.app_token else None
    return _request("POST", f"/api/v1/workflow/cancel/{args.record_id}", params=params)


def _cmd_replay(args) -> int:
    params: dict[str, Any] = {"fresh": "true" if args.fresh else "false"}
    if args.app_token:
        params["app_token"] = args.app_token
    return _request("POST", f"/api/v1/workflow/replay/{args.record_id}", params=params)


def _cmd_export(args) -> int:
    params: dict[str, Any] = {}
    if args.app_token:
        params["app_token"] = args.app_token
    url = f"{_api_base()}/api/v1/workflow/export/{args.record_id}"
    try:
        resp = httpx.get(url, headers=_headers(), params=params, timeout=60.0)
    except httpx.RequestError as exc:
        sys.stderr.write(f"NETWORK ERROR: {exc}\n")
        return 2
    if resp.status_code >= 400:
        sys.stderr.write(f"ERROR {resp.status_code}: {resp.text[:300]}\n")
        return 1
    if args.out:
        from pathlib import Path

        out_path = Path(args.out).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(resp.text, encoding="utf-8")
        sys.stderr.write(f"✓ Wrote {len(resp.text)} chars to {out_path}\n")
    else:
        sys.stdout.write(resp.text)
    return 0


def _cmd_audit(args) -> int:
    params: dict[str, Any] = {"limit": args.limit}
    if args.target:
        params["target"] = args.target
    if args.action_prefix:
        params["action_prefix"] = args.action_prefix
    return _request("GET", "/api/v1/workflow/audit", params=params)


def _cmd_seed(args) -> int:
    body: dict[str, Any] = {
        "app_token": args.app_token,
        "table_id": args.table_id,
        "title": args.title,
        "dimension": args.dimension or "综合分析",
        "background": args.background or "",
    }
    params = {"force": "true"} if args.force else None
    return _request("POST", "/api/v1/workflow/seed", json_body=body, params=params)


# ---- argparse 装配 ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Puff C21 multi-agent workflow CLI — 14 个端点的 headless 入口",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sub.add_parser("preflight", help="部署前置 4-check 体检").set_defaults(func=_cmd_preflight)

    p_setup = sub.add_parser("setup", help="一键创建 12 表 / 视图 / 模板中心")
    p_setup.add_argument("--name", default="内容运营虚拟组织")
    p_setup.add_argument("--mode", default="seed_demo")
    p_setup.add_argument("--base-type", default="validation")
    p_setup.add_argument("--apply-native", action="store_true")
    p_setup.set_defaults(func=_cmd_setup)

    p_start = sub.add_parser("start", help="启动调度循环")
    p_start.add_argument("--app-token", required=True)
    p_start.add_argument(
        "--table-ids",
        required=True,
        help='JSON 形如：\'{"task":"tbl_x","output":"tbl_y","report":"tbl_z","performance":"tbl_p"}\'',
    )
    p_start.add_argument("--interval", type=int, default=30)
    p_start.add_argument("--analysis-every", type=int, default=5)
    p_start.set_defaults(func=_cmd_start)

    sub.add_parser("stop", help="停止调度循环").set_defaults(func=_cmd_stop)

    p_status = sub.add_parser("status", help="查看运行状态")
    p_status.add_argument("--app-token", default=None)
    p_status.set_defaults(func=_cmd_status)

    sub.add_parser("telemetry", help="综合遥测：runner / 多租户 / LLM 用量 / SSE / 熔断器 / cancellation").set_defaults(func=_cmd_telemetry)

    sub.add_parser("agents", help="七岗 Agent 目录").set_defaults(func=_cmd_agents)

    p_profile = sub.add_parser("agent-profile", help="单 agent 完整画像")
    p_profile.add_argument("agent_id")
    p_profile.set_defaults(func=_cmd_agent_profile)

    p_similar = sub.add_parser("similar", help="跨任务相似度检索（长期记忆）")
    p_similar.add_argument("--title", required=True)
    p_similar.add_argument("--dimension", default="")
    p_similar.add_argument("--background", default="")
    p_similar.add_argument("--limit", type=int, default=3)
    p_similar.add_argument("--app-token", default=None)
    p_similar.set_defaults(func=_cmd_similar)

    p_cancel = sub.add_parser("cancel", help="主动取消 in-flight 任务")
    p_cancel.add_argument("--record-id", required=True)
    p_cancel.add_argument("--app-token", default=None)
    p_cancel.set_defaults(func=_cmd_cancel)

    p_replay = sub.add_parser("replay", help="复跑已完成 / 已取消的任务")
    p_replay.add_argument("--record-id", required=True)
    p_replay.add_argument("--app-token", default=None)
    p_replay.add_argument("--fresh", action="store_true", help="清 agent_cache 强制重打 LLM")
    p_replay.set_defaults(func=_cmd_replay)

    p_export = sub.add_parser("export", help="导出任务全量产出为 Markdown")
    p_export.add_argument("--record-id", required=True)
    p_export.add_argument("--app-token", default=None)
    p_export.add_argument("--out", default=None, help="输出文件路径，不传则 stdout")
    p_export.set_defaults(func=_cmd_export)

    p_audit = sub.add_parser("audit", help="查询审计日志")
    p_audit.add_argument("--target", default=None)
    p_audit.add_argument("--action-prefix", default=None)
    p_audit.add_argument("--limit", type=int, default=50)
    p_audit.set_defaults(func=_cmd_audit)

    p_seed = sub.add_parser("seed", help="向分析任务表写一条新待处理任务")
    p_seed.add_argument("--app-token", required=True)
    p_seed.add_argument("--table-id", required=True)
    p_seed.add_argument("--title", required=True)
    p_seed.add_argument("--dimension", default="综合分析")
    p_seed.add_argument("--background", default="")
    p_seed.add_argument("--force", action="store_true", help="跳过 dedup 保护")
    p_seed.set_defaults(func=_cmd_seed)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
