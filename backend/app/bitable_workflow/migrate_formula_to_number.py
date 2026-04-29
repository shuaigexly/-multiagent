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
from app.bitable_workflow.bitable_ops import _safe_json, _invalidate_field_cache
from app.bitable_workflow.schema import priority_score, health_score
from app.core.redaction import redact_sensitive_text
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
        raise RuntimeError(
            f"DELETE field {field_id} 失败 status={r.status_code} code={body.get('code')} "
            f"msg={redact_sensitive_text(body.get('msg'), max_chars=500)}"
        )


async def _rename_field(http: httpx.AsyncClient, app_token: str, table_id: str, field_id: str, new_name: str) -> str | None:
    """重命名 Number 字段（PUT /fields/{field_id}，type=2 必传）。"""
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    payload = {
        "field_name": new_name,
        "type": 2,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    }
    r = await http.put(
        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    body = _safe_json(r)
    if r.status_code != 200 or body.get("code") not in (0, None):
        raise RuntimeError(
            f"PUT field {field_id} 重命名失败 status={r.status_code} code={body.get('code')} "
            f"msg={redact_sensitive_text(body.get('msg'), max_chars=500)}"
        )
    return field_id


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
        raise RuntimeError(
            f"CREATE Number field {field_name!r} 失败 status={r.status_code} code={body.get('code')} "
            f"msg={redact_sensitive_text(body.get('msg'), max_chars=500)}"
        )
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

        # v8.6.20-r6：用「先建影子字段 → 删旧 → 重命名」替代「先删后建」，
        # 避免中途 CREATE 失败导致原字段彻底丢失。
        old_fid = target.get("field_id")
        shadow_name = f"{field_name}__migrating"
        # 防御：若上一次中途失败留了 shadow 字段，先清它
        stale_shadow = next((f for f in fields if f.get("field_name") == shadow_name), None)
        if stale_shadow:
            await _delete_field(http, app_token, tid, stale_shadow.get("field_id"))

        # 1. CREATE 影子 Number（成功后才碰旧字段）
        shadow_fid = await _create_number_field(http, app_token, tid, shadow_name)
        # v8.6.20-r7（审计 #6）：建/删/改字段后必须清 field_exists 缓存
        try:
            _invalidate_field_cache(app_token, tid)
        except Exception:
            pass
        print(f"  ✓ 已建影子字段 {shadow_name!r} ({shadow_fid})")

        # 2. 回填到影子字段（失败按 record 收集）
        records = await bitable_ops.list_records(app_token, tid, max_records=2000)
        bf_count = 0
        failed_record_ids: list[str] = []
        for r in records:
            rid = r.get("record_id")
            if not rid:
                continue
            f = r.get("fields") or {}
            src_val = _flatten(f.get(source_field))
            score = score_fn(src_val)
            try:
                await bitable_ops.update_record(app_token, tid, rid, {shadow_name: score})
                bf_count += 1
            except Exception as exc:
                logger.warning("回填 record=%s 失败: %s", rid, exc)
                failed_record_ids.append(rid)
        print(f"  ✓ 回填 {bf_count}/{len(records)} 条 record")

        # 失败率 > 50% 视为不可用，不删旧字段保留 shadow 给用户排查
        if records and len(failed_record_ids) > len(records) // 2:
            return {
                "table": table_name,
                "shadow_field_id": shadow_fid,
                "shadow_name": shadow_name,
                "old_field_id": old_fid,
                "backfilled": bf_count,
                "total_records": len(records),
                "failed_record_ids": failed_record_ids,
                "issues": [f"回填失败率 {len(failed_record_ids)}/{len(records)} > 50%，已停止；旧字段保留，影子字段未替换"],
            }

        # 3. DELETE 旧 Formula
        await _delete_field(http, app_token, tid, old_fid)
        try:
            _invalidate_field_cache(app_token, tid)
        except Exception:
            pass
        print(f"  ✓ 已删除原 Formula 字段 {old_fid}")

        # 4. 重命名影子 → 目标名（用 PUT /fields/{field_id}）
        # v8.6.20-r7（审计 #4）：rename 失败时，schema 处于「旧字段已删 + 影子字段名仍带
        # __migrating 后缀」的不一致中间态，scheduler 写「综合评分」会全部 silently strip。
        # 这里捕获 rename 异常，立即返回带 issues 的状态，让调用方/用户尽快人工救场（去
        # 飞书 UI 把影子字段重命名）。不再无脑 raise 葬送已经回填好的影子数据。
        try:
            renamed = await _rename_field(http, app_token, tid, shadow_fid, field_name)
            try:
                _invalidate_field_cache(app_token, tid)
            except Exception:
                pass
            print(f"  ✓ 已重命名影子字段 → {field_name!r}")
        except Exception as rename_exc:
            err = (
                f"DELETE 已成功但 RENAME 失败：{rename_exc}；"
                f"影子字段 '{shadow_name}' (id={shadow_fid}) 仍存在，请到飞书 UI 手工重命名为 '{field_name}'。"
            )
            logger.error(err)
            print(f"  ✗ {err}")
            return {
                "table": table_name,
                "old_field_id": old_fid,
                "shadow_field_id": shadow_fid,
                "shadow_name": shadow_name,
                "backfilled": bf_count,
                "total_records": len(records),
                "failed_record_ids": failed_record_ids,
                "issues": [err],
            }

        return {
            "table": table_name,
            "old_field_id": old_fid,
            "new_field_id": renamed or shadow_fid,
            "backfilled": bf_count,
            "total_records": len(records),
            "failed_record_ids": failed_record_ids,
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
