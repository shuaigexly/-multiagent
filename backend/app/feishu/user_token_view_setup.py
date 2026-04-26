"""用 user_access_token 走前端身份配置 kanban 分组 / gallery 封面。

背景：飞书 OpenAPI v1 用 tenant_access_token 调 PATCH /views 时，
group_field / cover_field 字段会被静默丢弃（实测过 5 种 payload + SDK 类型
声明确认）。但飞书前端能配，是因为它走 user_access_token。

用法（CLI）：
    python -m app.feishu.user_token_view_setup <app_token> <user_access_token>

获取 user_access_token：
    1. 登录 https://open.feishu.cn/app → 你的应用 → API 调试
    2. 选用户身份 + scope: bitable:app
    3. 点「生成 user_access_token」复制（30 分钟有效）

OAuth 完整流程的 redirect 端点见 app/api/auth.py（需配应用回调地址）。
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import httpx

from app.feishu.aily import get_feishu_open_base_url

logger = logging.getLogger(__name__)


# (table_name, view_name, view_type, target_field_name)
# group_field 用于 kanban；cover_field 用于 gallery
_VIEW_CONFIG: list[tuple[str, str, str, str]] = [
    # 分析任务
    ("分析任务", "📊 状态看板", "kanban", "状态"),
    ("分析任务", "📇 任务画册", "gallery", "任务图像"),
    # 岗位分析
    ("岗位分析", "👥 岗位看板", "kanban", "岗位角色"),
    ("岗位分析", "🩺 健康度画册", "gallery", "图表"),
    # 综合报告
    ("综合报告", "🚦 健康度看板", "kanban", "综合健康度"),
    # 数字员工效能
    ("数字员工效能", "🏅 岗位看板", "kanban", "岗位"),
]


async def configure_view_groups(
    app_token: str,
    user_access_token: str,
    base_url: Optional[str] = None,
) -> dict:
    """用 user_access_token 给所有 kanban/gallery 视图配 group_field / cover_field。

    返回 {"ok": [...], "failed": [...]}.
    """
    base = base_url or get_feishu_open_base_url()
    auth = {"Authorization": f"Bearer {user_access_token}", "Content-Type": "application/json"}
    auth_get = {"Authorization": f"Bearer {user_access_token}"}
    ok_list: list[str] = []
    failed_list: list[str] = []

    def _safe_json(resp: httpx.Response) -> dict:
        """v8.6.17：飞书 5xx/网关错误偶尔返回 HTML，r.json() 直接 raise 难定位。
        统一返回 {"code": -1, "msg": "..."} 让上层逻辑走错误分支。"""
        try:
            return resp.json()
        except Exception:
            return {
                "code": -1,
                "msg": f"non-JSON response (status={resp.status_code}): {resp.text[:200]!r}",
            }

    async def _paged_items(h: httpx.AsyncClient, url: str) -> list[dict]:
        items: list[dict] = []
        page_token: str | None = None
        while True:
            params: dict[str, object] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = await h.get(url, headers=auth_get, params=params)
            body = _safe_json(resp)
            if resp.status_code != 200 or body.get("code") != 0:
                raise RuntimeError(
                    f"paged list failed: status={resp.status_code} code={body.get('code')} msg={body.get('msg')}"
                )
            data = body.get("data") or {}
            items.extend(data.get("items") or [])
            if not data.get("has_more"):
                return items
            page_token = data.get("page_token") or data.get("next_page_token")
            if not page_token:
                raise RuntimeError("paged list failed: has_more=true but page_token missing")

    async with httpx.AsyncClient(timeout=30) as h:
        table_items = await _paged_items(h, f"{base}/open-apis/bitable/v1/apps/{app_token}/tables")
        tables = {t["name"]: t["table_id"] for t in table_items}

        for tname, vname, vtype, target_field in _VIEW_CONFIG:
            tid = tables.get(tname)
            if not tid:
                failed_list.append(f"{tname}/{vname}: 表不存在")
                continue

            try:
                fields = await _paged_items(
                    h,
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields",
                )
            except RuntimeError as exc:
                failed_list.append(f"{tname}/{vname}: list fields failed: {exc}")
                continue
            target_fid = next((f["field_id"] for f in fields if f.get("field_name") == target_field), None)
            if not target_fid:
                failed_list.append(f"{tname}/{vname}: 字段 {target_field!r} 不存在")
                continue

            try:
                views = await _paged_items(
                    h,
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/views",
                )
            except RuntimeError as exc:
                failed_list.append(f"{tname}/{vname}: list views failed: {exc}")
                continue
            view = next(
                (v for v in views
                 if v.get("view_name") == vname and v.get("view_type") == vtype),
                None,
            )
            if not view:
                failed_list.append(f"{tname}/{vname}: 视图不存在")
                continue

            # 试多种 payload — user_access_token 下飞书可能开放更多 property 字段
            payloads = []
            if vtype == "kanban":
                payloads = [
                    {"property": {"group_field_id": target_fid}},
                    {"property": {"kanban_field_id": target_fid}},
                    {"property": {"kanban": {"group_field_id": target_fid}}},
                    {"property": {"group_info": [{"field_id": target_fid, "desc": False}]}},
                ]
            else:  # gallery
                payloads = [
                    {"property": {"cover_field_id": target_fid}},
                    {"property": {"cover": {"field_id": target_fid}}},
                    {"property": {"cover_setting": {"field_id": target_fid}}},
                ]

            success = False
            for payload in payloads:
                rp = await h.patch(
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/views/{view['view_id']}",
                    headers=auth, json=payload,
                )
                pbody = _safe_json(rp)
                if rp.status_code == 200 and pbody.get("code") == 0:
                    # 验证是否生效（GET 后看 property）
                    rd = await h.get(
                        f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/views/{view['view_id']}",
                        headers=auth_get,
                    )
                    dbody = _safe_json(rd)
                    prop = (dbody.get("data") or {}).get("view", {}).get("property") or {}
                    # 看任意一个 key 出现 target_fid
                    flat = str(prop)
                    if target_fid in flat:
                        ok_list.append(f"{tname}/{vname}: payload={list(payload['property'].keys())[0]}")
                        success = True
                        break
            if not success:
                failed_list.append(
                    f"{tname}/{vname}: 4 种 payload 全部静默丢弃，user token 也不通"
                )

    return {"ok": ok_list, "failed": failed_list}


async def _cli() -> int:
    if len(sys.argv) < 3:
        print("用法: python -m app.feishu.user_token_view_setup <app_token> <user_access_token>")
        return 2
    app_token = sys.argv[1]
    user_token = sys.argv[2]
    res = await configure_view_groups(app_token, user_token)
    print(f"\n✅ 成功 ({len(res['ok'])}):")
    for s in res["ok"]:
        print(f"   {s}")
    if res["failed"]:
        print(f"\n❌ 失败 ({len(res['failed'])}):")
        for s in res["failed"]:
            print(f"   {s}")
    return 0 if not res["failed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_cli()))
