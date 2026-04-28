"""迭代审计工具 — 逐表 / 逐视图 / 逐字段 / 逐记录读取实际 UI 状态。

用法（CLI）：
    python -m app.bitable_workflow.verify <app_token>

或在测试中调用 audit_bitable(app_token) → 返回结构化 issues 列表。

设计原则：只看飞书 API 返回的真实状态，不基于本地 schema 自欺欺人地"以为"配好了。
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Optional

import httpx

from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token


async def _fetch(http: httpx.AsyncClient, url: str, token: str) -> dict:
    r = await http.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    data = r.json()
    if data.get("code") not in (None, 0):
        raise RuntimeError(f"Feishu API failed: code={data.get('code')} msg={data.get('msg')}")
    return data


async def _fetch_items(
    http: httpx.AsyncClient,
    url: str,
    token: str,
    *,
    page_size: int = 100,
) -> list[dict]:
    items: list[dict] = []
    page_token: str | None = None
    while True:
        params: dict[str, object] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        r = await http.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code") not in (None, 0):
            raise RuntimeError(f"Feishu API failed: code={data.get('code')} msg={data.get('msg')}")
        payload = data.get("data") or {}
        items.extend(payload.get("items") or [])
        if not payload.get("has_more"):
            return items
        page_token = payload.get("page_token") or payload.get("next_page_token")
        if not page_token:
            # v8.6.20-r10（审计 #5）：飞书部分 endpoint（views/dashboards）会在最后一页
            # 返回 has_more=true + 空 page_token，此时下一页其实是空。bitable_ops
            # 同样情况是 break，verify 之前 raise 会让整 audit 中途崩溃，掩盖真实
            # 问题列表。改为视作分页结束。
            return items


async def audit_bitable(
    app_token: str,
    expected_table_names: Optional[list[str]] = None,
) -> dict:
    """迭代审计一个 Bitable 的 UI 状态，返回结构化报告。

    返回 {
      "tables": [{ "name", "id", "fields", "views", "records_count", "issues" }],
      "global_issues": [...],
    }
    """
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    # v8.6.19：dashboards / warnings 不计入主 issues
    report: dict = {"tables": [], "global_issues": [], "dashboards": [], "warnings": []}

    async with httpx.AsyncClient(timeout=30) as http:
        tables = await _fetch_items(http, f"{base}/open-apis/bitable/v1/apps/{app_token}/tables", token)

        if expected_table_names:
            actual = {t["name"] for t in tables}
            missing = set(expected_table_names) - actual
            if missing:
                report["global_issues"].append(f"缺失表: {sorted(missing)}")

        for t in tables:
            tid = t["table_id"]
            tname = t["name"]
            tinfo: dict = {"name": tname, "id": tid, "issues": []}

            fields = await _fetch_items(
                http,
                f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields",
                token,
            )
            primary = [f for f in fields if f.get("is_primary")]
            if len(primary) != 1:
                tinfo["issues"].append(f"is_primary 字段数={len(primary)}（期望 1）")
            if primary and primary[0].get("type") != 1:
                tinfo["issues"].append(
                    f"主字段不是文本类型: {primary[0].get('field_name')!r} type={primary[0].get('type')}"
                )
            for f in fields:
                if f.get("field_name") in ("多行文本", "文本") and not f.get("is_primary"):
                    tinfo["issues"].append(f"残留默认字段 {f.get('field_name')!r}")
            tinfo["fields"] = [
                {
                    "name": f.get("field_name"),
                    "type": f.get("type"),
                    "ui": f.get("ui_type"),
                    "primary": bool(f.get("is_primary")),
                }
                for f in fields
            ]

            views_raw = await _fetch_items(
                http,
                f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/views",
                token,
            )
            views = []
            id_to_name = {f.get("field_id"): f.get("field_name") for f in fields}
            for v in views_raw:
                vid = v["view_id"]
                # v8.6.20-r2：form 视图正确详情端点是 /forms/{view_id} 而不是
                # /views/{view_id}（后者对 form 返回 400）。其他类型仍走 /views。
                fi: list[dict] = []
                try:
                    if v.get("view_type") == "form":
                        detail_resp = await _fetch(
                            http,
                            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/forms/{vid}",
                            token,
                        )
                        # form 详情含 shared_url；本字段不影响主 issues，存在 v 上即可
                        form_data = (detail_resp.get("data") or {}).get("form") or {}
                        v["shared_url"] = form_data.get("shared_url")
                        v["form_shared"] = form_data.get("shared")
                    else:
                        detail_resp = await _fetch(
                            http,
                            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/views/{vid}",
                            token,
                        )
                        detail = (detail_resp.get("data") or {}).get("view") or {}
                        prop = detail.get("property") or {}
                        fi = (prop.get("filter_info") or {}).get("conditions") or []
                except Exception as exc:
                    report.setdefault("warnings", []).append(
                        f"获取视图详情失败 {tname}/{v.get('view_name')!r} ({v.get('view_type')}): {exc}"
                    )
                view_entry = {
                    "id": vid,
                    "name": v["view_name"],
                    "type": v["view_type"],
                    "filter_conditions": [
                        {
                            "field": id_to_name.get(c.get("field_id"), "?"),
                            "op": c.get("operator"),
                            "value": c.get("value"),
                        }
                        for c in fi
                    ],
                }
                # v8.6.20-r2：form 视图额外暴露 shared_url
                if v.get("view_type") == "form" and v.get("shared_url"):
                    view_entry["shared_url"] = v["shared_url"]
                views.append(view_entry)
            tinfo["views"] = views

            records = await _fetch_items(
                http,
                f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/records",
                token,
                page_size=50,
            )
            tinfo["records_count"] = len(records)

            primary_field_name = primary[0].get("field_name") if primary else None
            if primary_field_name:
                empty_primary = 0
                for row in records:
                    f = row.get("fields") or {}
                    val = f.get(primary_field_name)
                    if isinstance(val, list):
                        val = "".join(x.get("text", "") for x in val if isinstance(x, dict))
                    if not val:
                        empty_primary += 1
                if empty_primary:
                    tinfo["issues"].append(
                        f"{empty_primary} 条记录主字段为空（UI 显示「未命名」）"
                    )

            report["tables"].append(tinfo)

        # v8.6.19：尝试列 dashboards（仅 list 可读，飞书 OpenAPI 不开放创建/编辑）
        # 失败仅入 warnings，不污染主 issues
        try:
            from app.feishu.dashboard_picker import list_dashboards
            report["dashboards"] = await list_dashboards(app_token)
        except Exception as exc:
            report["warnings"].append(f"列 dashboards 失败（非致命）: {exc}")

    return report


def _print_report(report: dict) -> int:
    """打印人类可读报告，返回 issue 总数。"""
    total = len(report.get("global_issues") or [])
    for g in report.get("global_issues") or []:
        print(f"❌ {g}")

    for t in report.get("tables") or []:
        print(f"\n## 表「{t['name']}」({t['id']})")
        print(f"  字段：{len(t['fields'])} 个")
        primary = next((f for f in t["fields"] if f["primary"]), None)
        print(f"  主字段：{primary['name'] if primary else '?'!r} type={primary['type'] if primary else '?'}")
        print(f"  视图：{len(t['views'])} 个")
        for v in t["views"]:
            cond = v["filter_conditions"]
            tag = ""
            if cond:
                tag = f" filter: {cond[0]['field']} {cond[0]['op']} {cond[0]['value']!r}"
            print(f"    {v['type']:8s} {v['name']!r:30s}{tag}")
        print(f"  记录数：{t['records_count']}")
        for i in t["issues"]:
            print(f"  ❌ {i}")
            total += 1

    # v8.6.19：dashboards / warnings 不计入主 issues
    dashboards = report.get("dashboards") or []
    if dashboards:
        print(f"\n## 仪表盘（{len(dashboards)}）")
        for d in dashboards:
            print(f"  {d.get('block_id', '?'):20s} {d.get('name', '?')!r}")
    warnings = report.get("warnings") or []
    if warnings:
        print(f"\n## 非致命 warnings ({len(warnings)})")
        for w in warnings:
            print(f"  ⚠️ {w}")

    print(f"\n总问题数：{total}")
    return total


async def _cli() -> int:
    if len(sys.argv) < 2:
        print("用法: python -m app.bitable_workflow.verify <app_token>")
        return 2
    app_token = sys.argv[1]
    expected = ["分析任务", "岗位分析", "综合报告", "数字员工效能"]
    report = await audit_bitable(app_token, expected_table_names=expected)
    issues = _print_report(report)
    return 0 if issues == 0 else 1


if __name__ == "__main__":
    # v8.6.20-r5：Windows 默认 stdout=GBK 遇到 emoji（🕐/🟢/...）会 UnicodeEncodeError，
    # 跟 repair_option_drift.py / migrate_formula_to_number.py 一致用 utf-8 包装。
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
    sys.exit(asyncio.run(_cli()))
