"""v8.6.20-r4：把存量 base 的 Formula(20) 字段迁移到 Number(2) + 回填值。

背景：
  v8.6.19 → v8.6.20 实测发现飞书 Formula `IF(.CONTAIN("P0"),100,...)` 在
  SingleSelect 字段上不生效（永远命中默认分支）。schema 已改为 Number 字段
  + scheduler/runner/write_agent_outputs 主动写值。

但既有 base 的「综合评分」「健康度数值」字段已经创建为 Formula(20)，
`_ensure_table_fields` 只 add 缺失字段，不能改类型 → 老 base 永远显示
全 25 / 全 0。

修复策略（破坏性，需用户授权）：
  1. DELETE Formula 字段（type=20）
  2. POST 重建为 Number（type=2）
  3. 遍历 record，按 priority_score(优先级) / health_score(健康度评级) 回填

CLI:
  python -m app.bitable_workflow.migrate_formula_to_number <app_token> [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import httpx

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.bitable_ops import _safe_json
from app.bitable_workflow.schema import priority_score, health_score
from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token

logger = logging.getLogger(__name__)


# (table_name, field_name, source_field, score_fn) 三元组
_MIGRATIONS = [
    ("分析任务", "综合评分", "优先级", priority_score),
    ("岗位分析", "健康度数值", "健康度评级", health_score),
]


async def _list_table_id(http: httpx.AsyncClient, app_token: str, name: str) -> str | None:
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    r = await http.get(
        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = _safe_json(r)
    for t in (body.get("data") or {}).get("items") or []:
        if t.get("name") == name:
            return t.get("table_id")
    return None


async def _list_fields(http: httpx.AsyncClient, app_token: str, table_id: str) -> list[dict]:
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    r = await http.get(
        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = _safe_json(r)
    return (body.get("data") or {}).get("items") or []


async def _delete_field(http: httpx.AsyncClient, app_token: str, table_id: str, field_id: str) -> None:
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    r = await http.delete(
        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = _safe_json(r)
    if r.status_code != 200 or body.get("code") not in (0, None):
        raise RuntimeError(f"DELETE field {field_id} 失败 status={r.status_code} code={body.get('code')} msg={body.get('msg')}")


async def _create_number_field(http: httpx.AsyncClient, app_token: str, table_id: str, field_name: str) -> str:
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    payload = {
        "field_name": field_name,
        "type": 2,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    }
    r = await http.post(
        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    body = _safe_json(r)
    if r.status_code != 200 or body.get("code") not in (0, None):
        raise RuntimeError(f"CREATE Number field {field_name!r} 失败 status={r.status_code} code={body.get('code')} msg={body.get('msg')}")
    return ((body.get("data") or {}).get("field") or {}).get("field_id", "")


def _flatten(value):
    if isinstance(value, list):
        return "".join(seg.get("text", "") for seg in value if isinstance(seg, dict))
    return str(value or "")


async def migrate_one(
    app_token: str,
    table_name: str,
    field_name: str,
    source_field: str,
    score_fn,
    dry_run: bool = False,
) -> dict:
    async with httpx.AsyncClient(timeout=30) as http:
        tid = await _list_table_id(http, app_token, table_name)
        if not tid:
            return {"table": table_name, "skipped": True, "reason": "table 不存在"}

        fields = await _list_fields(http, app_token, tid)
        target = next((f for f in fields if f.get("field_name") == field_name), None)
        if not target:
            return {"table": table_name, "skipped": True, "reason": f"字段 {field_name!r} 不存在"}

        if target.get("type") == 2:
            return {"table": table_name, "skipped": True, "reason": "已是 Number 类型"}

        if target.get("type") != 20:
            return {
                "table": table_name, "skipped": True,
                "reason": f"字段 {field_name!r} 类型={target.get('type')}（既非 Formula 也非 Number，不处理）",
            }

        print(f"[migrate] 表 {table_name}.{field_name}: Formula(20) → Number(2)")
        if dry_run:
            return {"table": table_name, "dry_run": True, "field_id": target.get("field_id")}

        # 1. DELETE Formula
        await _delete_field(http, app_token, tid, target.get("field_id"))
        print(f"  ✓ 已删除 Formula 字段 {target.get('field_id')}")

        # 2. CREATE Number
        new_fid = await _create_number_field(http, app_token, tid, field_name)
        print(f"  ✓ 已重建 Number 字段 {new_fid}")

        # 3. 回填
        records = await bitable_ops.list_records(app_token, tid, max_records=2000)
        bf_count = 0
        for r in records:
            rid = r.get("record_id")
            if not rid:
                continue
            f = r.get("fields") or {}
            src_val = _flatten(f.get(source_field))
            score = score_fn(src_val)
            try:
                await bitable_ops.update_record(app_token, tid, rid, {field_name: score})
                bf_count += 1
            except Exception as exc:
                logger.warning("回填 record=%s 失败: %s", rid, exc)
        print(f"  ✓ 回填 {bf_count}/{len(records)} 条 record")

        return {
            "table": table_name,
            "old_field_id": target.get("field_id"),
            "new_field_id": new_fid,
            "backfilled": bf_count,
            "total_records": len(records),
        }


async def migrate_all(app_token: str, dry_run: bool = False) -> list[dict]:
    results = []
    for table_name, field_name, source_field, score_fn in _MIGRATIONS:
        try:
            res = await migrate_one(app_token, table_name, field_name, source_field, score_fn, dry_run=dry_run)
        except Exception as exc:
            res = {"table": table_name, "error": str(exc)}
        results.append(res)
    return results


async def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app_token")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"[migrate-formula-to-number] base={args.app_token} dry_run={args.dry_run}")
    results = await migrate_all(args.app_token, dry_run=args.dry_run)
    print(f"\n===== 迁移结果 =====")
    for r in results:
        print(f"  {r}")
    return 0 if all(not r.get("error") for r in results) else 1


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
    sys.exit(asyncio.run(_cli()))
