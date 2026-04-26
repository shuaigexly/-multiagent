"""
工作流运行器（七岗多智能体版）

setup_workflow()     — 在飞书创建多维表格 App + 四张业务表，并写入初始分析任务
run_workflow_loop()  — 持续运行调度循环，定期触发七岗 DAG 分析流水线
stop_workflow()      — 停止循环
"""
import asyncio
import logging
import threading
from typing import Optional

from app.bitable_workflow import bitable_ops, schema
from app.bitable_workflow.schema import agent_output_fields, report_fields
from app.bitable_workflow.scheduler import run_one_cycle
from app.feishu.bitable import create_bitable, create_table, create_view

logger = logging.getLogger(__name__)

_running = False
_stop_event: Optional[asyncio.Event] = None
_state_lock = threading.Lock()


async def setup_workflow(name: str = "内容运营虚拟组织") -> dict:
    """
    一键初始化：
    1. 创建飞书多维表格 App
    2. 建四张表：分析任务 / 岗位分析 / 综合报告 / 数字员工效能
    3. 写入 4 条初始分析任务（覆盖内容战略、数据复盘、增长优化、产品规划四个维度）

    返回 {"app_token", "url", "table_ids": {"task", "output", "report", "performance"}}
    """
    result = await create_bitable(name)
    app_token = result["app_token"]

    # v8.6.18 — setup 中途任意步骤失败 → 自动 DELETE 整个 base 回滚（避免污染云空间）
    # codex 实测发现注入 _create_extra_views 抛错后会留下 6 张表 + 飞书自动「数据表」
    # 残留。这里把 create_bitable 之后的所有逻辑包在 try/except，失败时自动调
    # DELETE /drive/v1/files/{app_token}?type=bitable 把整个 base 删掉，确保
    # 上层调用方要么拿到完整可用的 base，要么什么都没有。
    try:
        task_tid = await create_table(app_token, schema.TABLE_TASK, schema.TASK_FIELDS)
        # 岗位分析表和综合报告表通过关联字段（type=18）与分析任务表建立表间关系
        output_tid = await create_table(app_token, schema.TABLE_AGENT_OUTPUT, agent_output_fields(task_tid))
        report_tid = await create_table(app_token, schema.TABLE_REPORT, report_fields(task_tid))
        performance_tid = await create_table(app_token, schema.TABLE_PERFORMANCE, schema.PERFORMANCE_FIELDS)
        # v8.6.16 — 第 5 张表「📚 数据源库」：每行一个数据集，分析任务通过名称引用
        datasource_tid = await create_table(app_token, schema.TABLE_DATASOURCE, schema.DATASOURCE_FIELDS)

        # 为每张表创建附加视图（看板/画册）以提升可视化效果
        # 每张表的第一个视图是默认网格视图（创建表时自动生成），这里追加额外视图
        await _create_extra_views(app_token, task_tid, output_tid, report_tid, performance_tid)

        # v8.6.2 修复：飞书新建多维表格 App 时会自动创建一张「数据表」作为默认表，
        # 用户打开 base URL 默认进的就是这张空表 → 看到一片空白以为整个 Bitable 没数据。
        # 同时各业务表里也会保留默认主字段「多行文本」（rename 没生效或 Feishu API 行为变化），
        # 看起来像一列空数据。统一在 setup 末尾把这些清理掉。
        await _cleanup_auto_created_artifacts(
            app_token,
            keep_table_ids={task_tid, output_tid, report_tid, performance_tid, datasource_tid},
        )
    except Exception as setup_exc:
        logger.error("setup_workflow failed mid-way, rolling back base %s: %s", app_token, setup_exc)
        await _delete_base_best_effort(app_token)
        raise

    # v8.6.20 — Formula 路径已废弃（实测综合评分 8/8=25 / 健康度数值 42/42=0
    # 全是默认值，飞书公式 .CONTAIN 在 SingleSelect 字段上不生效）。改为 Number
    # 字段 + scheduler/runner/write_agent_outputs 主动写值，100% 可控。
    # _create_formula_fields 函数保留但不再调用，留作未来公式语法可靠时复用。

    # v8.6.18 — 数据写入也要补偿：如果 SEED/数据源写入中途挂了，DELETE 整个 base
    try:
        await _populate_base_records(
            app_token, task_tid, datasource_tid,
        )
    except Exception as populate_exc:
        logger.error("populate base records failed, rolling back %s: %s", app_token, populate_exc)
        await _delete_base_best_effort(app_token)
        raise

    logger.info("Workflow setup complete: app_token=%s url=%s", app_token, result["url"])
    return {
        "app_token": app_token,
        "url": result["url"],
        "table_ids": {
            "task": task_tid,
            "output": output_tid,
            "report": report_tid,
            "performance": performance_tid,
            "datasource": datasource_tid,
        },
    }


async def _populate_base_records(app_token: str, task_tid: str, datasource_tid: str) -> None:
    """v8.6.18：把数据源表 + 引导 + SEED 任务写入抽出来，便于 setup_workflow 包补偿。"""
    from app.bitable_workflow.demo_data import DATASETS, csv_to_markdown
    for ds_name, ds_type, field_doc, csv_text in DATASETS:
        n_rows = max(0, len([ln for ln in csv_text.strip().splitlines() if ln.strip()]) - 1)
        await bitable_ops.create_record(
            app_token, datasource_tid,
            {
                "数据集名称": ds_name,
                "类型": ds_type,
                "字段说明": field_doc,
                "原始 CSV": csv_text,
                "渲染表格": csv_to_markdown(csv_text),
                "数据行数": n_rows,
            },
        )

    # v8.6.14：先写一条 UI 配置引导记录（已归档状态，不参与分析），再写 SEED 任务。
    # 飞书 OpenAPI 不公开 kanban.group_field / gallery.cover_field，必须用户在 UI
    # 上 1 次点击配置；飞书前端会持久化记住选择，下次进来自动分组。
    await bitable_ops.create_record(
        app_token, task_tid,
        {
            "任务标题": "📌 使用提示：看板/画册首次 UI 配置指引（请勿删）",
            "分析维度": "综合分析",
            "优先级": "P0 紧急",
            "状态": "已归档",
            "进度": 1.0,
            "背景说明": (
                "📌 看板/画册视图的一次性 UI 配置（飞书 OpenAPI 限制，无法编程实现）：\n\n"
                "【分析任务/📊 状态看板】点顶部「分组依据」→ 选「状态」字段\n"
                "【分析任务/📇 任务画册】点顶部「封面字段」→ 选「任务图像」\n"
                "【岗位分析/👥 岗位看板】点顶部「分组依据」→ 选「岗位角色」\n"
                "【岗位分析/🩺 健康度画册】点顶部「封面字段」→ 选「图表」附件\n"
                "【综合报告/🚦 健康度看板】点顶部「分组依据」→ 选「综合健康度」\n"
                "【综合报告/📋 报告画册】点顶部「封面字段」→ 选「图表」附件（无则留空）\n"
                "【数字员工效能/🏅 岗位看板】点顶部「分组依据」→ 选「岗位」\n\n"
                "⚠️ 飞书 OpenAPI v1 不公开 kanban.group_field / gallery.cover_field 接口"
                "（飞书 SDK AppTableViewProperty 类型声明只有 filter_info/hidden_fields/"
                "hierarchy_config，应用层 tenant_access_token 调 PATCH 这两个字段会被"
                "静默丢弃，仅 user_access_token 走前端 OAuth 才能配）。"
                "一次手动点选后飞书会持久化记忆，下次进来自动生效。"
            ),
        },
    )

    # v8.6.18 — 数据源字段同时存「人看的 markdown 表格」+「机器解析的原始 CSV」。
    # 飞书 PC/Web 客户端 text 字段会把 markdown 表格渲染成可视化表格，
    # CSV 留在最末段供 agent 的 data_parser 识别。
    # 围栏带 csv 语言标记（codex 验收 Top 5 #5），workflow_agents 正则 (?:csv)? 兼容。
    for title, dimension, background, data_source in schema.SEED_TASKS:
        rendered = (
            f"{csv_to_markdown(data_source)}\n\n"
            f"---\n_原始 CSV（agent 解析用，请勿编辑下方原始数据格式）：_\n```csv\n"
            f"{data_source}\n```"
        )
        await bitable_ops.create_record_optional_fields(
            app_token,
            task_tid,
            {
                "任务标题": title,
                "分析维度": dimension,
                "优先级": "P1 高",
                "状态": schema.Status.PENDING,
                "进度": 0,
                "背景说明": background,
                "数据源": rendered,
                # v8.6.20：综合评分由 priority_score() 算出（替代飞书公式不生效）
                "综合评分": schema.priority_score("P1 高"),
            },
            optional_keys=["综合评分"],
        )


async def _delete_base_best_effort(app_token: str) -> None:
    """v8.6.18：setup_workflow 中途失败时调 DELETE /drive/v1/files 删除整个 base。
    任何失败仅 warn，不抛（已经在 except 里）。"""
    import httpx
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    try:
        base = get_feishu_open_base_url()
        token = await get_tenant_access_token()
        async with httpx.AsyncClient(timeout=15) as h:
            r = await h.delete(
                f"{base}/open-apis/drive/v1/files/{app_token}",
                headers={"Authorization": f"Bearer {token}"},
                params={"type": "bitable"},
            )
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:200]}
            if r.status_code >= 400 or body.get("code", 0) != 0:
                logger.warning(
                    "rollback DELETE base failed: status=%s code=%s msg=%s",
                    r.status_code, body.get("code"), body.get("msg"),
                )
            else:
                logger.info("rollback: DELETE base %s success", app_token)
    except Exception as exc:
        logger.warning("rollback DELETE base raised: %s", exc)


async def _cleanup_auto_created_artifacts(app_token: str, keep_table_ids: set[str]) -> None:
    """删除飞书自动创建的「数据表」+ 各业务表的「多行文本」垃圾字段。

    飞书行为：
      1. 新建多维表格 App 时自动创建一张默认表（名称通常为"数据表"）
      2. 业务表创建后保留默认主字段（名称通常为"多行文本"）—— 即使 SDK rename 调用成功，
         有时也会留下这条字段（与 Feishu API 行为变化有关）

    这两类"自动产物"会让 UI 显示一堆空字段/空表，让 base URL 进去看到一片空白。
    keep_table_ids: 我们刚建的 4 张业务表 id；不在这个集合的表都视为飞书自动产物，删除。
    """
    import httpx

    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token

    base = get_feishu_open_base_url()
    try:
        token = await get_tenant_access_token()
    except Exception as exc:
        logger.warning("cleanup skipped — token fetch failed: %s", exc)
        return

    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15.0) as http:
        # 第 1 步：列出所有表，删除非业务表（飞书自动建的「数据表」）
        try:
            r = await http.get(
                f"{base}/open-apis/bitable/v1/apps/{app_token}/tables",
                headers=headers,
            )
            tables = r.json().get("data", {}).get("items", []) or []
        except Exception as exc:
            logger.warning("cleanup tables list failed: %s", exc)
            tables = []

        for tb in tables:
            tid = tb.get("table_id")
            tname = tb.get("name", "")
            if not tid or tid in keep_table_ids:
                continue
            try:
                rd = await http.delete(
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}",
                    headers=headers,
                )
                logger.info("Cleaned up auto-created table: %s (%s) status=%s", tname, tid, rd.status_code)
            except Exception as exc:
                logger.warning("Failed to delete table %s: %s", tid, exc)

        # 第 2 步：删除非主字段的「多行文本」遗留（v8.6.3 起 _ensure_table_fields 已正确
        # rename 主字段，本步骤主要兜底处理可能残留的非主字段同名条目，例如某些环境下
        # rename 失败导致同时存在主字段和重复字段。注意：飞书禁止删除 is_primary=True 的字段。
        for tid in keep_table_ids:
            try:
                rf = await http.get(
                    f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields",
                    headers=headers,
                )
                fields = rf.json().get("data", {}).get("items", []) or []
            except Exception as exc:
                logger.warning("cleanup fields list failed table=%s: %s", tid, exc)
                continue

            for f in fields:
                fname = f.get("field_name", "")
                fid = f.get("field_id")
                is_primary = f.get("is_primary", False)
                # 只删非主字段的「多行文本」（主字段无法删除，且现在已被 rename）
                if fname == "多行文本" and fid and not is_primary:
                    try:
                        rd = await http.delete(
                            f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields/{fid}",
                            headers=headers,
                        )
                        logger.info("Cleaned up non-primary 多行文本 field: table=%s field=%s status=%s",
                                    tid, fid, rd.status_code)
                    except Exception as exc:
                        logger.warning("Failed to delete 多行文本 field: %s", exc)


async def _create_extra_views(
    app_token: str,
    task_tid: str,
    output_tid: str,
    report_tid: str,
    performance_tid: str,
) -> None:
    """为四张业务表创建看板/画册/过滤视图，提升多维表格视觉可读性。

    v8.6.4 真相：飞书 OpenAPI 不公开 kanban group_info / gallery cover_field_id
    （PATCH /views 试 group_info、kanban_field_id、group_field_id 全部 200 OK
    但被静默丢弃；hidden_fields 在 kanban/gallery 上 1254019 显式拒绝）。
    可编程的 property 仅 filter_info / hierarchy_config / hidden_fields(grid)。

    因此本版本：
      - 仍创建 kanban / gallery（首次打开会被 UI 自动选第一个 SingleSelect/Attachment 字段）
      - 额外提供「过滤型 grid 视图」做兜底 — 它们 100% 通过 API 配置成功，开箱即用
      - 不再尝试 PATCH group/cover（避免误导日志）

    单次视图创建失败不应阻塞整体 setup — 静默降级即可。
    """
    # v8.6.13 — 同时建 grid filter 视图（API 可配，开箱即用）+ kanban / gallery
    # 视觉视图（API 不能配 group_field/cover_field 但视图保留，用户在飞书 UI 上点
    # 一次"分组依据"/"封面字段"即生效，下次打开飞书会持久化记住选择）。
    # 不再删除 kanban / gallery — 删了等于丢失视图槽位，用户要靠它们做汇报演示。
    view_plan: list[tuple[str, str, str, str | None, str | None]] = [
        # 分析任务 — filter grid 切片
        (task_tid, "🕐 待分析", "grid", "状态", "待分析"),
        (task_tid, "⚙️ 分析中", "grid", "状态", "分析中"),
        (task_tid, "✅ 已完成", "grid", "状态", "已完成"),
        (task_tid, "🔥 P0 紧急", "grid", "优先级", "P0 紧急"),
        (task_tid, "📌 P1 高优", "grid", "优先级", "P1 高"),
        (task_tid, "📊 状态看板", "kanban", None, None),  # UI 选「状态」做分组
        (task_tid, "📇 任务画册", "gallery", None, None),  # UI 选「任务图像」做封面
        # 岗位分析 — filter grid + 视觉视图
        (output_tid, "🟢 健康岗位", "grid", "健康度评级", "🟢 健康"),
        (output_tid, "🟡 关注岗位", "grid", "健康度评级", "🟡 关注"),
        (output_tid, "🔴 预警岗位", "grid", "健康度评级", "🔴 预警"),
        (output_tid, "👥 岗位看板", "kanban", None, None),  # UI 选「岗位角色」做分组
        (output_tid, "🩺 健康度画册", "gallery", None, None),  # UI 选「图表」附件做封面
        # 综合报告 — filter grid + 视觉视图
        (report_tid, "🟢 健康报告", "grid", "综合健康度", "🟢 健康"),
        (report_tid, "🟡 关注报告", "grid", "综合健康度", "🟡 关注"),
        (report_tid, "🔴 预警报告", "grid", "综合健康度", "🔴 预警"),
        (report_tid, "🚦 健康度看板", "kanban", None, None),  # UI 选「综合健康度」分组
        (report_tid, "📋 报告画册", "gallery", None, None),
        # 效能表 — 视觉视图
        (performance_tid, "🏅 岗位看板", "kanban", None, None),  # UI 选「岗位」做分组
        (performance_tid, "🏆 效能画册", "gallery", None, None),
        # v8.6.19 — 甘特视图（用户首次打开 UI 选「创建时间→完成日期」做时间轴）
        (task_tid, "📅 任务甘特", "gantt", None, None),
        # v8.6.19 — 表单视图（创建后调 _share_form_view 拿 shared_url）
        (task_tid, "📥 需求收集表", "form", None, None),
    ]
    for table_id, name, vtype, filter_field, filter_value in view_plan:
        try:
            view_id = await create_view(
                app_token, table_id, name, vtype,
                filter_field=filter_field, filter_value=filter_value,
            )
            # v8.6.19 — form 视图建好后尽力共享，得到 shared_url
            if vtype == "form" and view_id:
                shared_url = await _share_form_view(app_token, table_id, view_id)
                if shared_url:
                    logger.info("Form view %r shared at %s", name, shared_url)
        except Exception as exc:
            logger.warning("创建视图失败 table=%s name=%s: %s", table_id, name, exc)


# ===== v8.6.19 Phase A.2 — Formula 字段 deferred creation =====

async def _create_formula_fields(app_token: str, task_tid: str, output_tid: str) -> None:
    """v8.6.19：在普通字段建好后创建 Formula 字段。

    必须 deferred 因为公式表达式要用 field_id 引用 `bitable::$table[tid].$field[fid]`，
    field_id 只有字段创建后才能拿到。

    任一公式字段失败仅 logger.warning + 失效字段缓存，不阻塞 setup（公式是 optional capability）。
    """
    import httpx
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    from app.bitable_workflow.bitable_ops import _safe_json, _invalidate_field_cache
    from app.bitable_workflow.schema import FORMULA_FIELD_TYPE

    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def _list_field_id_map(tid: str) -> dict[str, str]:
        url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields"
        async with httpx.AsyncClient(timeout=15) as h:
            r = await h.get(url, headers={"Authorization": f"Bearer {token}"})
            body = _safe_json(r)
            if r.status_code != 200 or body.get("code") != 0:
                raise RuntimeError(
                    f"list fields failed: status={r.status_code} code={body.get('code')} msg={body.get('msg')}"
                )
            items = (body.get("data") or {}).get("items") or []
            return {f["field_name"]: f["field_id"] for f in items if f.get("field_name")}

    async def _create_formula(tid: str, field_name: str, expression: str) -> None:
        url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{tid}/fields"
        payload = {
            "field_name": field_name,
            "type": FORMULA_FIELD_TYPE,
            "ui_type": "Formula",
            "property": {"formula_expression": expression},
        }
        async with httpx.AsyncClient(timeout=15) as h:
            r = await h.post(url, headers=auth, json=payload)
            body = _safe_json(r)
            if r.status_code != 200 or body.get("code") != 0:
                raise RuntimeError(
                    f"create formula field {field_name!r} failed: "
                    f"status={r.status_code} code={body.get('code')} msg={body.get('msg')}"
                )
        logger.info("Formula field %r created on table %s", field_name, tid)

    # 1. 综合评分（task 表，仅基于优先级 — 不乘进度，避免待分析任务全 0 同分）
    try:
        task_fids = await _list_field_id_map(task_tid)
        priority_fid = task_fids.get("优先级")
        if not priority_fid:
            raise RuntimeError("「优先级」字段在 task 表中不存在")
        expr = (
            f'IF(bitable::$table[{task_tid}].$field[{priority_fid}].CONTAIN("P0"),100,'
            f'IF(bitable::$table[{task_tid}].$field[{priority_fid}].CONTAIN("P1"),75,'
            f'IF(bitable::$table[{task_tid}].$field[{priority_fid}].CONTAIN("P2"),50,25)))'
        )
        await _create_formula(task_tid, "综合评分", expr)
    except Exception as exc:
        logger.warning("综合评分 公式字段创建失败 (non-fatal): %s", exc)
    finally:
        _invalidate_field_cache(app_token, task_tid)

    # 2. 健康度数值（output 表，依赖 健康度评级）
    try:
        output_fids = await _list_field_id_map(output_tid)
        health_fid = output_fids.get("健康度评级")
        if not health_fid:
            raise RuntimeError("「健康度评级」字段在 output 表中不存在")
        expr = (
            f'IF(bitable::$table[{output_tid}].$field[{health_fid}].CONTAIN("健康"),100,'
            f'IF(bitable::$table[{output_tid}].$field[{health_fid}].CONTAIN("关注"),60,'
            f'IF(bitable::$table[{output_tid}].$field[{health_fid}].CONTAIN("预警"),20,0)))'
        )
        await _create_formula(output_tid, "健康度数值", expr)
    except Exception as exc:
        logger.warning("健康度数值 公式字段创建失败 (non-fatal): %s", exc)
    finally:
        _invalidate_field_cache(app_token, output_tid)


async def _share_form_view(app_token: str, table_id: str, view_id: str) -> str | None:
    """v8.6.19：尝试 PATCH 表单 metadata 设 shared=true，并 GET 拿 shared_url。

    失败仅 logger.warning + return None，不阻塞 setup。
    """
    import httpx
    from app.feishu.aily import get_feishu_open_base_url, get_tenant_access_token
    from app.bitable_workflow.bitable_ops import _safe_json

    base = get_feishu_open_base_url()
    token = await get_tenant_access_token()
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"{base}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/forms/{view_id}"

    try:
        async with httpx.AsyncClient(timeout=15) as h:
            r = await h.patch(url, headers=auth, json={"shared": True})
            body = _safe_json(r)
            if r.status_code != 200 or body.get("code") != 0:
                logger.warning(
                    "PATCH form metadata failed: status=%s code=%s msg=%s",
                    r.status_code, body.get("code"), body.get("msg"),
                )
                return None
            # 部分接口在 PATCH 响应里就有 shared_url，部分需要再 GET
            form_data = (body.get("data") or {}).get("form") or {}
            shared_url = form_data.get("shared_url")
            if shared_url:
                return shared_url
            r2 = await h.get(url, headers={"Authorization": f"Bearer {token}"})
            body2 = _safe_json(r2)
            form_data = (body2.get("data") or {}).get("form") or {}
            return form_data.get("shared_url")
    except Exception as exc:
        logger.warning("_share_form_view failed (non-fatal): %s", exc)
        return None


def mark_starting() -> bool:
    """Atomically mark the loop as starting before the background task fires.

    Returns True if the transition succeeded (was idle), False if already running.
    Call this in the API handler immediately before scheduling the background task
    so that a second concurrent /start request sees is_running()=True and is rejected.
    """
    global _running
    with _state_lock:
        if _running:
            return False
        _running = True
        return True


async def run_workflow_loop(
    app_token: str,
    table_ids: dict,
    interval: int = 30,
    analysis_every: int = 5,  # kept for API compatibility; analysis is now per-task in pipeline
) -> None:
    """
    持续运行七岗多智能体调度循环。

    每轮调用 run_one_cycle()，对所有「待分析」任务执行完整的七岗 DAG 流水线：
    Wave1（5个并行Agent）→ Wave2（财务顾问）→ Wave3（CEO助理综合）
    """
    global _running, _stop_event
    with _state_lock:
        _running = True  # belt-and-suspenders; mark_starting() already set this
    _stop_event = asyncio.Event()
    cycle = 0
    logger.info("Workflow loop started (interval=%ds)", interval)

    try:
        while _running:
            cycle += 1
            try:
                processed = await run_one_cycle(app_token, table_ids)
                logger.info("Cycle %d: processed %d tasks", cycle, processed)
            except Exception as exc:
                logger.error("Workflow cycle %d error: %s", cycle, exc)

            # Interruptible sleep: wakes immediately if stop_workflow() is called
            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=float(interval))
                break  # stop_event was set — exit loop without waiting full interval
            except asyncio.TimeoutError:
                pass  # normal interval elapsed, continue
    finally:
        with _state_lock:
            _running = False
            _stop_event = None

    logger.info("Workflow loop stopped after %d cycles", cycle)


def stop_workflow() -> None:
    global _running
    with _state_lock:
        _running = False
    if _stop_event is not None:
        _stop_event.set()


def is_running() -> bool:
    with _state_lock:
        return _running
