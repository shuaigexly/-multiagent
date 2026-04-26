"""v8.6.20：修复飞书 SingleSelect option_id 漂移问题（实测 base #3 bug）。

背景：
  飞书 SingleSelect 字段写入时若 value 含不可见字符 / 空白漂移 / 任何 schema 外的
  字符串，飞书会"看似匹配实则新建 option"。GET 出来 string 看似一致，但内部
  option_id 不同，filter 视图按 option_id 过滤就会漏掉这些 record。
  实测 base PR41b365raO4RlsznRUc8CVtnRh 的「健康度评级」字段：实际 32 条「🟡 关注」
  但 filter 视图只命中 20 条 → 12 条绑了 hidden option_id。

修复策略：
  对每条岗位分析 record，**显式 PUT 一次「健康度评级」字段**：
  - 把 GET 出来的当前值（看似已是 schema label）原样写回 → 飞书重新匹配 option_id
  - 如果命中 schema option，更新到 canonical id；如果是 hidden option，看是否能合并

CLI：
  python -m app.bitable_workflow.repair_option_drift <app_token> [--table <table_id>]
                                                     [--field <field_name>]
                                                     [--dry-run]

默认修复「健康度评级」字段。可指定其他 SingleSelect 字段重用。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import httpx

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.bitable_ops import _safe_json
from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token

logger = logging.getLogger(__name__)


# 默认修复对象：岗位分析表的「健康度评级」字段
_DEFAULT_TABLE_NAMES = ("岗位分析",)
_DEFAULT_FIELD = "健康度评级"
_HEALTH_ALLOWED = {"🟢 健康", "🟡 关注", "🔴 预警", "⚪ 数据不足"}


async def _list_table_id(app_token: str, table_name: str) -> str | None:
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get(
            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = _safe_json(r)
        for t in (body.get("data") or {}).get("items") or []:
            if t.get("name") == table_name:
                return t.get("table_id")
    return None


async def _list_field_options(app_token: str, table_id: str, field_name: str) -> tuple[str | None, list[dict]]:
    """返回 (field_id, options[{id,name,color}])"""
    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get(
            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = _safe_json(r)
        for f in (body.get("data") or {}).get("items") or []:
            if f.get("field_name") == field_name:
                return f.get("field_id"), (f.get("property") or {}).get("options") or []
    return None, []


async def repair_option_drift(
    app_token: str,
    table_id: str | None = None,
    table_name: str = "岗位分析",
    field_name: str = _DEFAULT_FIELD,
    allowed: set[str] = _HEALTH_ALLOWED,
    dry_run: bool = False,
) -> dict:
    """对指定 SingleSelect 字段做 option_id 漂移修复。

    返回 {"scanned": int, "rewritten": int, "skipped": int, "issues": [...]}
    """
    if table_id is None:
        table_id = await _list_table_id(app_token, table_name)
        if not table_id:
            return {"scanned": 0, "rewritten": 0, "skipped": 0,
                    "issues": [f"表 {table_name!r} 不存在"]}

    field_id, options = await _list_field_options(app_token, table_id, field_name)
    if not field_id:
        return {"scanned": 0, "rewritten": 0, "skipped": 0,
                "issues": [f"字段 {field_name!r} 不存在"]}

    canonical_names = {opt.get("name"): opt.get("id") for opt in options}
    print(f"[repair] 表 {table_name} ({table_id}) 字段 {field_name}")
    print(f"[repair] 当前 options ({len(options)}):")
    for opt in options:
        marker = " ⭐ schema" if opt.get("name") in allowed else " ⚠️ hidden"
        print(f"  {opt.get('id'):18s} {opt.get('name')!r:20s}{marker}")

    # 拉所有 record
    records = await bitable_ops.list_records(app_token, table_id, max_records=2000)
    print(f"[repair] 共 {len(records)} 条 record")

    rewritten = 0
    skipped = 0
    issues: list[str] = []
    for r in records:
        rid = r.get("record_id")
        if not rid:
            continue
        f = r.get("fields") or {}
        cur_value = f.get(field_name)
        # 富文本拍平兜底
        if isinstance(cur_value, list):
            cur_value = "".join(seg.get("text", "") for seg in cur_value if isinstance(seg, dict))
        if not isinstance(cur_value, str):
            skipped += 1
            continue
        cur_clean = cur_value.strip()
        # 移除 invisible 字符
        for ch in ("​", "‌", "‍", "﻿", " "):
            cur_clean = cur_clean.replace(ch, "")
        # 严格映射到 schema 内 label
        if cur_clean in allowed:
            target = cur_clean
        else:
            # 不在 allowed → 找最相似的（含 emoji 模糊匹配）
            target = None
            for label in allowed:
                if label[0] == cur_clean[0:1]:  # emoji 第一字符匹配
                    target = label
                    break
            if not target:
                issues.append(f"record {rid}: value {cur_value!r} 无法映射到任何 schema label")
                skipped += 1
                continue

        # 写回（即使值看起来相同也写一次，让飞书重新匹配 option_id）
        if dry_run:
            print(f"  [DRY] {rid}: {cur_value!r} → {target!r}")
            rewritten += 1
            continue
        try:
            await bitable_ops.update_record(app_token, table_id, rid, {field_name: target})
            rewritten += 1
        except Exception as exc:
            issues.append(f"record {rid} 写回失败: {exc}")
            skipped += 1

    return {
        "scanned": len(records),
        "rewritten": rewritten,
        "skipped": skipped,
        "issues": issues,
    }


async def _cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app_token")
    parser.add_argument("--table", default="岗位分析",
                        help='表名（默认「岗位分析」）')
    parser.add_argument("--field", default=_DEFAULT_FIELD,
                        help=f'SingleSelect 字段名（默认 {_DEFAULT_FIELD!r}）')
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印不写")
    args = parser.parse_args()

    result = await repair_option_drift(
        args.app_token,
        table_name=args.table,
        field_name=args.field,
        dry_run=args.dry_run,
    )
    print(f"\n===== 修复结果 =====")
    print(f"  扫描: {result['scanned']} 条")
    print(f"  改写: {result['rewritten']} 条")
    print(f"  跳过: {result['skipped']} 条")
    if result.get("issues"):
        print(f"  问题: {len(result['issues'])} 项")
        for i in result["issues"][:10]:
            print(f"    - {i}")
    return 0 if not result.get("issues") else 1


if __name__ == "__main__":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
    sys.exit(asyncio.run(_cli()))
