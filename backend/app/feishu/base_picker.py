"""列出当前用户/企业可访问的多维表格（base）→ 提示选 base → 提示选表 → 返回字段映射。

用 user_access_token 走前端身份调 drive API（tenant_access_token 看不到用户私有
云空间，必须用 user token）。配合 v8.6.15 的 OAuth flow 使用。

CLI 用法：
    python -m app.feishu.base_picker

模块用法：
    from app.feishu.base_picker import list_user_bases, pick_base_interactive
    bases = await list_user_bases(user_token)  # → [{"app_token", "name", "url"}, ...]
    info = await pick_base_interactive(user_token)  # 交互式 → {"app_token","table_id","fields":[...]}

REST API 见 app/api/feishu_oauth.py 的 GET /oauth/list-bases。
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import httpx

from app.feishu.aily import get_feishu_open_base_url

logger = logging.getLogger(__name__)


async def list_user_bases(
    user_access_token: str,
    folder_token: Optional[str] = None,
    page_size: int = 50,
) -> list[dict]:
    """列出 user 云空间根目录（或指定 folder_token）下的所有多维表格。

    返回 [{"app_token", "name", "url", "modified_time", "owner_id"}, ...]
    """
    base = get_feishu_open_base_url()
    auth = {"Authorization": f"Bearer {user_access_token}"}
    bases: list[dict] = []
    page_token: Optional[str] = None

    async with httpx.AsyncClient(timeout=20) as h:
        while True:
            params = {"page_size": page_size}
            if folder_token:
                params["folder_token"] = folder_token
            if page_token:
                params["page_token"] = page_token
            r = await h.get(f"{base}/open-apis/drive/v1/files", headers=auth, params=params)
            body = r.json()
            if r.status_code != 200 or body.get("code") != 0:
                raise RuntimeError(
                    f"list files failed: status={r.status_code} code={body.get('code')} "
                    f"msg={body.get('msg')}"
                )
            data = body.get("data") or {}
            for f in data.get("files") or []:
                if f.get("type") != "bitable":
                    continue
                bases.append({
                    "app_token": f.get("token"),
                    "name": f.get("name"),
                    "url": f.get("url"),
                    "modified_time": f.get("modified_time"),
                    "owner_id": f.get("owner_id"),
                })
            if not data.get("has_more"):
                break
            page_token = data.get("next_page_token")
            if not page_token:
                break
    return bases


async def list_tables(app_token: str, user_access_token: str) -> list[dict]:
    """列指定 base 下的所有表。返回 [{"table_id", "name", "revision"}, ...]"""
    base = get_feishu_open_base_url()
    auth = {"Authorization": f"Bearer {user_access_token}"}
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get(f"{base}/open-apis/bitable/v1/apps/{app_token}/tables", headers=auth)
        body = r.json()
        if r.status_code != 200 or body.get("code") != 0:
            raise RuntimeError(f"list tables failed: code={body.get('code')} msg={body.get('msg')}")
        return body.get("data", {}).get("items") or []


async def list_fields(app_token: str, table_id: str, user_access_token: str) -> list[dict]:
    """列指定表下的所有字段。返回 [{"field_id", "field_name", "type", "ui_type", "is_primary"}, ...]"""
    base = get_feishu_open_base_url()
    auth = {"Authorization": f"Bearer {user_access_token}"}
    async with httpx.AsyncClient(timeout=15) as h:
        r = await h.get(
            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=auth,
        )
        body = r.json()
        if r.status_code != 200 or body.get("code") != 0:
            raise RuntimeError(f"list fields failed: code={body.get('code')} msg={body.get('msg')}")
        return body.get("data", {}).get("items") or []


async def pick_base_interactive(user_access_token: str) -> dict:
    """CLI 交互式选 base + 表 + 字段。返回 {"app_token", "table_id", "table_name", "fields": [...]}"""
    print("\n📂 正在拉取你云空间的多维表格列表...")
    bases = await list_user_bases(user_access_token)
    if not bases:
        print("❌ 未找到任何多维表格。请先在飞书云空间创建一个，或检查 user_access_token 权限。")
        sys.exit(1)

    print(f"\n找到 {len(bases)} 个多维表格：\n")
    for i, b in enumerate(bases, 1):
        print(f"  [{i}] {b['name']!r}")
        print(f"      app_token={b['app_token']}  modified={b.get('modified_time') or '?'}")

    while True:
        choice = input(f"\n请输入序号选 base [1-{len(bases)}]: ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(bases):
                break
        except ValueError:
            pass
        print(f"❌ 无效序号，请输 1-{len(bases)}")

    chosen_base = bases[idx - 1]
    app_token = chosen_base["app_token"]
    print(f"\n✅ 已选 base: {chosen_base['name']!r} ({app_token})")

    print(f"\n📑 正在拉取表清单...")
    tables = await list_tables(app_token, user_access_token)
    if not tables:
        print("❌ 该 base 下无表。")
        sys.exit(1)

    print(f"\n找到 {len(tables)} 张表：\n")
    for i, t in enumerate(tables, 1):
        print(f"  [{i}] {t.get('name')!r}  table_id={t.get('table_id')}")

    while True:
        choice = input(f"\n请输入序号选表 [1-{len(tables)}]: ").strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(tables):
                break
        except ValueError:
            pass
        print(f"❌ 无效序号，请输 1-{len(tables)}")

    chosen_table = tables[idx - 1]
    table_id = chosen_table["table_id"]
    print(f"\n✅ 已选表: {chosen_table.get('name')!r}")

    print(f"\n📋 正在拉取字段清单...")
    fields = await list_fields(app_token, table_id, user_access_token)
    print(f"\n字段（{len(fields)} 个）:")
    for f in fields:
        primary = " ★PRIMARY" if f.get("is_primary") else ""
        opts = (f.get("property") or {}).get("options") or []
        opts_tag = f" opts=[{', '.join(o.get('name', '?') for o in opts[:3])}{'...' if len(opts) > 3 else ''}]" if opts else ""
        print(f"  {f.get('field_id'):16s} {f.get('field_name')!r:18s} type={f.get('type'):4} ui={f.get('ui_type')}{opts_tag}{primary}")

    return {
        "app_token": app_token,
        "base_name": chosen_base["name"],
        "table_id": table_id,
        "table_name": chosen_table.get("name"),
        "fields": fields,
    }


async def _cli() -> int:
    if len(sys.argv) < 2:
        print(
            "用法：\n"
            "  python -m app.feishu.base_picker <user_access_token>\n\n"
            "获取 user_access_token：先走 OAuth flow（项目里 oauth_minimal.py 或者\n"
            "POST /api/v1/feishu/oauth/url + callback 自动存 DB；或调试用临时 token 复制）。"
        )
        return 2
    user_token = sys.argv[1]
    info = await pick_base_interactive(user_token)
    print(f"\n===== 选择结果 =====")
    print(f"  app_token = {info['app_token']}")
    print(f"  table_id  = {info['table_id']}")
    print(f"  字段数    = {len(info['fields'])}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli()))
