"""
工作流运行器（七岗多智能体版）

setup_workflow()     — 在飞书创建多维表格 App + 多张业务表，并写入初始分析任务
run_workflow_loop()  — 持续运行调度循环，定期触发七岗 DAG 分析流水线
stop_workflow()      — 停止循环
"""
import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from app.bitable_workflow import bitable_ops, schema
from app.bitable_workflow.native_manifest import build_native_manifest
from app.bitable_workflow.native_specs import (
    build_automation_specs,
    build_dashboard_specs,
    build_form_spec,
    build_role_specs,
    build_workflow_specs,
)
from app.bitable_workflow.schema import agent_output_fields, report_fields
from app.bitable_workflow.scheduler import run_one_cycle
from app.core.redaction import redact_sensitive_text
from app.feishu.bitable import create_bitable, create_table, create_view

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "v8.6.20-r6"
DEFAULT_SETUP_MODE = "seed_demo"
DEFAULT_BASE_TYPE = "validation"
NATIVE_ASSET_STATES = {
    "blueprint_ready": "已生成蓝图，但尚未在飞书云侧创建原生对象",
    "api_supported": "官方能力支持，待后续接入自动创建",
    "created": "当前 setup 已在 Base 中创建完成",
    "manual_finish_required": "需要在飞书 UI 里补完最后一步",
    "permission_blocked": "当前权限不足，无法继续创建或共享",
}

_running = False
_stop_event: Optional[asyncio.Event] = None
_state_lock = threading.Lock()


async def setup_workflow(
    name: str = "内容运营虚拟组织",
    *,
    mode: str = DEFAULT_SETUP_MODE,
    base_type: str = DEFAULT_BASE_TYPE,
) -> dict:
    """
    一键初始化：
    1. 创建飞书多维表格 App
    2. 建多张表：分析任务 / 岗位分析 / 综合报告 / 数字员工效能 / 数据源库 / 证据链 / 产出评审 / 交付动作 / 复核历史 / 交付结果归档 / 自动化日志 / 模板配置中心
    3. 写入 4 条初始分析任务（覆盖内容战略、数据复盘、增长优化、产品规划四个维度）

    返回 {"app_token", "url", "table_ids": {...}}
    """
    result = await create_bitable(name)
    app_token = result["app_token"]
    initialized_at = datetime.now(tz=timezone.utc).isoformat()
    base_meta = {
        "base_type": base_type,
        "mode": mode,
        "schema_version": SCHEMA_VERSION,
        "initialized_at": initialized_at,
        "source_template": "feishu-bitable-native-delivery-loop",
    }

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
        evidence_tid = await create_table(app_token, schema.TABLE_EVIDENCE, schema.EVIDENCE_FIELDS)
        review_tid = await create_table(app_token, schema.TABLE_REVIEW, schema.REVIEW_FIELDS)
        action_tid = await create_table(app_token, schema.TABLE_ACTION, schema.ACTION_FIELDS)
        review_history_tid = await create_table(app_token, schema.TABLE_REVIEW_HISTORY, schema.REVIEW_HISTORY_FIELDS)
        archive_tid = await create_table(app_token, schema.TABLE_DELIVERY_ARCHIVE, schema.DELIVERY_ARCHIVE_FIELDS)
        automation_log_tid = await create_table(app_token, schema.TABLE_AUTOMATION_LOG, schema.AUTOMATION_LOG_FIELDS)
        template_tid = await create_table(app_token, schema.TABLE_TEMPLATE_CENTER, schema.TEMPLATE_CENTER_FIELDS)

        # 为每张表创建附加视图（看板/画册）以提升可视化效果
        # 每张表的第一个视图是默认网格视图（创建表时自动生成），这里追加额外视图
        view_assets = await _create_extra_views(
            app_token,
            task_tid,
            output_tid,
            report_tid,
            performance_tid,
            evidence_tid,
            review_tid,
            action_tid,
            review_history_tid,
            archive_tid,
            automation_log_tid,
            template_tid,
        ) or {"views": [], "forms": []}

        # v8.6.2 修复：飞书新建多维表格 App 时会自动创建一张「数据表」作为默认表，
        # 用户打开 base URL 默认进的就是这张空表 → 看到一片空白以为整个 Bitable 没数据。
        # 同时各业务表里也会保留默认主字段「多行文本」（rename 没生效或 Feishu API 行为变化），
        # 看起来像一列空数据。统一在 setup 末尾把这些清理掉。
        await _cleanup_auto_created_artifacts(
            app_token,
            keep_table_ids={
                task_tid, output_tid, report_tid, performance_tid, datasource_tid, evidence_tid, review_tid,
                action_tid, review_history_tid, archive_tid, automation_log_tid, template_tid,
            },
        )
    except Exception as setup_exc:
        logger.error(
            "setup_workflow failed mid-way, rolling back base %s: %s",
            redact_sensitive_text(f"app_token={app_token}"),
            redact_sensitive_text(setup_exc, max_chars=500),
        )
        await _delete_base_best_effort(app_token)
        raise

    # v8.6.20 — Formula 路径已废弃（实测综合评分 8/8=25 / 健康度数值 42/42=0
    # 全是默认值，飞书公式 .CONTAIN 在 SingleSelect 字段上不生效）。改为 Number
    # 字段 + scheduler/runner/write_agent_outputs 主动写值，100% 可控。
    # _create_formula_fields 函数保留但不再调用，留作未来公式语法可靠时复用。

    # v8.6.18 — 数据写入也要补偿：如果 SEED/数据源写入中途挂了，DELETE 整个 base
    try:
        await _populate_base_records(
            app_token,
            task_tid,
            datasource_tid,
            template_tid,
            mode=mode,
            base_meta=base_meta,
        )
    except Exception as populate_exc:
        logger.error(
            "populate base records failed, rolling back %s: %s",
            redact_sensitive_text(f"app_token={app_token}"),
            redact_sensitive_text(populate_exc, max_chars=500),
        )
        await _delete_base_best_effort(app_token)
        raise

    table_ids = {
        "task": task_tid,
        "output": output_tid,
        "report": report_tid,
        "performance": performance_tid,
        "datasource": datasource_tid,
        "evidence": evidence_tid,
        "review": review_tid,
        "action": action_tid,
        "review_history": review_history_tid,
        "archive": archive_tid,
        "automation_log": automation_log_tid,
        "template": template_tid,
    }
    native_assets = _build_native_assets(
        app_token=app_token,
        base_url=result["url"],
        table_ids=table_ids,
        view_assets=view_assets,
        base_meta=base_meta,
    )
    native_manifest = build_native_manifest(
        app_token=app_token,
        base_url=result["url"],
        table_ids=table_ids,
        base_meta=base_meta,
        native_assets=native_assets,
    )

    logger.info(
        "Workflow setup complete: app_token=%s url=%s",
        redact_sensitive_text(f"app_token={app_token}"),
        redact_sensitive_text(result["url"]),
    )
    return {
        "app_token": app_token,
        "url": result["url"],
        "table_ids": table_ids,
        "base_meta": base_meta,
        "native_assets": native_assets,
        "native_manifest": native_manifest,
    }


async def _populate_base_records(
    app_token: str,
    task_tid: str,
    datasource_tid: str,
    template_tid: str,
    *,
    mode: str,
    base_meta: dict,
) -> None:
    """v8.6.18：把数据源表 + 引导 + SEED 任务写入抽出来，便于 setup_workflow 包补偿。"""
    from app.bitable_workflow.demo_data import DATASETS, csv_to_markdown
    if mode == "seed_demo":
        for ds_name, ds_type, field_doc, csv_text in DATASETS:
            n_rows = max(0, len([ln for ln in csv_text.strip().splitlines() if ln.strip()]) - 1)
            await bitable_ops.create_record(
                app_token, datasource_tid,
                {
                    "数据集名称": ds_name,
                    "类型": ds_type,
                    "字段说明": field_doc,
                    "数据来源": "系统内置演示数据",
                    "可信等级": "medium",
                    "适用任务类型": "经营分析/增长优化/综合分析",
                    "原始 CSV": csv_text,
                    "渲染表格": csv_to_markdown(csv_text),
                    "数据行数": n_rows,
                    "最近校验说明": "初始化导入",
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
            "输出目的": "汇报展示",
            "任务来源": "手工创建",
            "业务归属": "综合经营",
            "汇报对象级别": "部门管理层",
            "状态": "已归档",
            "进度": 1.0,
            "背景说明": (
                "📌 看板/画册视图的一次性 UI 配置（飞书 OpenAPI 限制，无法编程实现）：\n\n"
                "【分析任务/📊 状态看板】点顶部「分组依据」→ 选「状态」字段\n"
                "【分析任务/🧭 工作流路由】点顶部「分组依据」→ 选「工作流路由」字段\n"
                "【分析任务/📇 任务画册】点顶部「封面字段」→ 选「任务图像」\n"
                "【岗位分析/👥 岗位看板】点顶部「分组依据」→ 选「岗位角色」\n"
                "【岗位分析/🩺 健康度画册】点顶部「封面字段」→ 选「图表」附件\n"
                "【综合报告/🚦 健康度看板】点顶部「分组依据」→ 选「综合健康度」\n"
                "【综合报告/📋 报告画册】点顶部「封面字段」→ 选「图表」附件（无则留空）\n"
                "【数字员工效能/🏅 岗位看板】点顶部「分组依据」→ 选「岗位」\n\n"
                f"📦 当前 Base 元信息：type={base_meta['base_type']} / mode={base_meta['mode']} / "
                f"schema={base_meta['schema_version']} / initialized_at={base_meta['initialized_at']}\n\n"
                "📌 推荐在多维表格里继续配置 3 条原生自动化：\n"
                "1. 当「待发送汇报」= 是时，发送飞书群消息/邮件，正文使用「工作流消息包」\n"
                "2. 当「待创建执行任务」= 是时，创建飞书任务，正文使用「工作流执行包」\n"
                "3. 当「待安排复核」= 是时，在「建议复核时间」触发提醒或创建复核任务\n\n"
                "⚠️ 飞书 OpenAPI v1 不公开 kanban.group_field / gallery.cover_field 接口"
                "（飞书 SDK AppTableViewProperty 类型声明只有 filter_info/hidden_fields/"
                "hierarchy_config，应用层 tenant_access_token 调 PATCH 这两个字段会被"
                "静默丢弃，仅 user_access_token 走前端 OAuth 才能配）。"
                "一次手动点选后飞书会持久化记忆，下次进来自动生效。"
            ),
            "目标对象": "系统管理员",
            "成功标准": "用户能看懂视图用途并完成首次 UI 配置",
            "自动化执行状态": "已完成",
        },
    )

    # v8.6.18 — 数据源字段同时存「人看的 markdown 表格」+「机器解析的原始 CSV」。
    # 飞书 PC/Web 客户端 text 字段会把 markdown 表格渲染成可视化表格，
    # CSV 留在最末段供 agent 的 data_parser 识别。
    # 围栏带 csv 语言标记（codex 验收 Top 5 #5），workflow_agents 正则 (?:csv)? 兼容。
    if mode == "seed_demo":
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
                    "输出目的": "经营诊断",
                    "任务来源": "手工创建",
                    "业务归属": "综合经营",
                    "汇报对象级别": "负责人",
                    "状态": schema.Status.PENDING,
                    "进度": 0,
                    "背景说明": background,
                    "数据源": rendered,
                    "自动化执行状态": "未触发",
                    # v8.6.20：综合评分由 priority_score() 算出（替代飞书公式不生效）
                    "综合评分": schema.priority_score("P1 高"),
                },
                optional_keys=["综合评分", "任务来源", "业务归属", "汇报对象级别", "自动化执行状态"],
            )

    template_seed_rows = [
        {
            "模板名称": "直接汇报默认模板",
            "适用工作流路由": "直接汇报",
            "适用输出目的": "汇报展示",
            "汇报模板": (
                "任务：{task_title}\n"
                "对象：{audience}\n"
                "结论：{one_liner}\n"
                "摘要：{management_summary}\n"
                "风险：{risk}\n"
                "建议执行：{execute_items}"
            ),
            "执行模板": "路由：{route}\n当前以汇报为主，无额外执行任务。",
            "默认汇报对象": "CEO",
            "默认汇报对象OpenID": "",
            "默认拍板负责人": "CEO",
            "默认拍板负责人OpenID": "",
            "默认复盘负责人": "经营复盘负责人",
            "默认复盘负责人OpenID": "",
            "模板说明": "适用于直接汇报场景的简版管理摘要模板",
            "启用": True,
        },
        {
            "模板名称": "等待拍板默认模板",
            "适用工作流路由": "等待拍板",
            "适用输出目的": "管理决策",
            "汇报模板": (
                "任务：{task_title}\n"
                "对象：{audience}\n"
                "需拍板事项：{decision_items}\n"
                "摘要：{management_summary}\n"
                "风险：{risk}"
            ),
            "执行模板": "请围绕以下拍板项准备：\n{decision_items}",
            "默认汇报对象": "CEO/管理层",
            "默认汇报对象OpenID": "",
            "默认拍板负责人": "CEO/管理层",
            "默认拍板负责人OpenID": "",
            "默认复盘负责人": "经营复盘负责人",
            "默认复盘负责人OpenID": "",
            "模板说明": "适用于等待拍板场景",
            "启用": True,
        },
        {
            "模板名称": "直接执行默认模板",
            "适用工作流路由": "直接执行",
            "适用输出目的": "执行跟进",
            "汇报模板": (
                "任务：{task_title}\n"
                "执行负责人：{execution_owner}\n"
                "结论：{one_liner}\n"
                "建议执行：{execute_items}"
            ),
            "执行模板": (
                "任务：{task_title}\n"
                "路由：{route}\n"
                "执行负责人：{execution_owner}\n"
                "执行项：{execute_items}\n"
                "管理摘要：{management_summary}"
            ),
            "默认执行负责人": "待指派",
            "默认执行负责人OpenID": "",
            "默认复盘负责人": "执行复盘负责人",
            "默认复盘负责人OpenID": "",
            "模板说明": "适用于直接执行场景",
            "启用": True,
        },
        {
            "模板名称": "补数复核默认模板",
            "适用工作流路由": "补数复核",
            "适用输出目的": "补数核验",
            "汇报模板": (
                "任务：{task_title}\n"
                "当前结论：{one_liner}\n"
                "需补数事项：{need_data_items}\n"
                "复核负责人：{review_owner}"
            ),
            "执行模板": (
                "任务：{task_title}\n"
                "复核负责人：{review_owner}\n"
                "需补数事项：{need_data_items}\n"
                "评审动作：{review_action}"
            ),
            "默认复核负责人": "待指派",
            "默认复核负责人OpenID": "",
            "默认复盘负责人": "数据复盘负责人",
            "默认复盘负责人OpenID": "",
            "默认复核SLA小时": 24,
            "模板说明": "适用于补数复核场景",
            "启用": True,
        },
        {
            "模板名称": "重新分析默认模板",
            "适用工作流路由": "重新分析",
            "适用输出目的": "管理决策",
            "汇报模板": (
                "任务：{task_title}\n"
                "当前结论不稳定，建议重新分析。\n"
                "原因：{review_action}\n"
                "风险：{risk}"
            ),
            "执行模板": (
                "任务：{task_title}\n"
                "重新分析负责人：{review_owner}\n"
                "需补数事项：{need_data_items}"
            ),
            "默认复核负责人": "待指派",
            "默认复核负责人OpenID": "",
            "默认复盘负责人": "重跑复盘负责人",
            "默认复盘负责人OpenID": "",
            "默认复核SLA小时": 4,
            "模板说明": "适用于建议重跑场景",
            "启用": True,
        },
    ]
    for row in template_seed_rows:
        await bitable_ops.create_record_optional_fields(
            app_token,
            template_tid,
            row,
            optional_keys=[
                "适用工作流路由",
                "适用输出目的",
                "执行模板",
                "默认汇报对象",
                "默认汇报对象OpenID",
                "默认拍板负责人",
                "默认拍板负责人OpenID",
                "默认执行负责人",
                "默认执行负责人OpenID",
                "默认复核负责人",
                "默认复核负责人OpenID",
                "默认复盘负责人",
                "默认复盘负责人OpenID",
                "默认复核SLA小时",
                "模板说明",
            ],
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
                    r.status_code, body.get("code"), redact_sensitive_text(body.get("msg"), max_chars=500),
                )
            else:
                logger.info(
                    "rollback: DELETE base %s success",
                    redact_sensitive_text(f"app_token={app_token}"),
                )
    except Exception as exc:
        logger.warning("rollback DELETE base raised: %s", redact_sensitive_text(exc, max_chars=500))


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
        logger.warning("cleanup skipped — token fetch failed: %s", redact_sensitive_text(exc, max_chars=500))
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
    evidence_tid: str,
    review_tid: str,
    action_tid: str,
    review_history_tid: str,
    archive_tid: str,
    automation_log_tid: str,
    template_tid: str,
) -> dict:
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
        (task_tid, "🟢 可直接汇报", "grid", "最新评审动作", "直接采用"),
        (task_tid, "🟡 待补数复核", "grid", "最新评审动作", "补数后复核"),
        (task_tid, "🔁 建议重跑", "grid", "最新评审动作", "建议重跑"),
        (task_tid, "📣 待发送汇报", "grid", "待发送汇报", "True"),
        (task_tid, "🧾 待创建执行任务", "grid", "待创建执行任务", "True"),
        (task_tid, "🗓 待安排复核", "grid", "待安排复核", "True"),
        (task_tid, "👔 拍板人任务", "grid", "待拍板确认", "True"),
        (task_tid, "⚙️ 执行人任务", "grid", "待执行确认", "True"),
        (task_tid, "🧪 复核人任务", "grid", "待安排复核", "True"),
        (task_tid, "🔁 待进入复盘", "grid", "待复盘确认", "True"),
        (task_tid, "⏳ 待拍板确认", "grid", "待拍板确认", "True"),
        (task_tid, "🚀 待执行落地", "grid", "待执行确认", "True"),
        (task_tid, "🔁 已进入复盘", "grid", "是否进入复盘", "True"),
        (task_tid, "🧭 当前责任角色", "kanban", None, None),
        (task_tid, "🟨 需关注任务", "grid", "异常状态", "需关注"),
        (task_tid, "🟥 已异常任务", "grid", "异常状态", "已异常"),
        (task_tid, "🟨 责任人待指派", "grid", "异常类型", "责任人待指派"),
        (task_tid, "🟥 拍板滞留", "grid", "异常类型", "拍板滞留"),
        (task_tid, "🟥 执行超期", "grid", "异常类型", "执行超期"),
        (task_tid, "🟧 复核超时", "grid", "异常类型", "复核超时"),
        (task_tid, "🟪 复盘滞留", "grid", "异常类型", "复盘滞留"),
        (task_tid, "🧭 工作流路由", "kanban", None, None),
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
        # 证据链 — 重点看风险/机会与证据类型
        (evidence_tid, "🧱 硬证据", "grid", "证据等级", "硬证据"),
        (evidence_tid, "🟡 待验证", "grid", "证据等级", "待验证"),
        (evidence_tid, "⚠️ 风险证据", "grid", "证据用途", "risk"),
        (evidence_tid, "🚀 机会证据", "grid", "证据用途", "opportunity"),
        (evidence_tid, "🧾 证据类型看板", "kanban", None, None),
        # 产出评审 — 重点看推荐动作
        (review_tid, "✅ 直接采用", "grid", "推荐动作", "直接采用"),
        (review_tid, "🟡 补数后复核", "grid", "推荐动作", "补数后复核"),
        (review_tid, "🔁 建议重跑", "grid", "推荐动作", "建议重跑"),
        (review_tid, "🧪 评审看板", "kanban", None, None),
        # 交付动作
        (action_tid, "📣 汇报动作", "grid", "动作类型", "发送汇报"),
        (action_tid, "✅ 已完成动作", "grid", "动作状态", "已完成"),
        (action_tid, "❌ 失败动作", "grid", "动作状态", "执行失败"),
        (action_tid, "🧭 动作路由", "kanban", None, None),
        # 复核历史
        (review_history_tid, "🟡 补数复核历史", "grid", "推荐动作", "补数后复核"),
        (review_history_tid, "🔁 重跑历史", "grid", "推荐动作", "建议重跑"),
        (review_history_tid, "✅ 直接采用历史", "grid", "推荐动作", "直接采用"),
        (review_history_tid, "🧪 复核轮次看板", "kanban", None, None),
        # 交付归档
        (archive_tid, "📬 待汇报归档", "grid", "归档状态", "待汇报"),
        (archive_tid, "🧾 待执行归档", "grid", "归档状态", "待执行"),
        (archive_tid, "🔁 待复盘归档", "grid", "归档状态", "待复盘"),
        (archive_tid, "🗓 待复核归档", "grid", "归档状态", "待复核"),
        (archive_tid, "⏳ 待拍板归档", "grid", "归档状态", "待拍板"),
        (archive_tid, "📦 归档看板", "kanban", None, None),
        # 自动化日志
        (automation_log_tid, "✅ 成功日志", "grid", "执行状态", "已完成"),
        (automation_log_tid, "🛠 待补完日志", "grid", "执行状态", "待补完"),
        (automation_log_tid, "❌ 失败日志", "grid", "执行状态", "执行失败"),
        (automation_log_tid, "⏭ 跳过日志", "grid", "执行状态", "已跳过"),
        (automation_log_tid, "🪵 节点日志看板", "kanban", None, None),
        # 模板配置中心
        (template_tid, "🧩 汇报模板", "grid", "适用工作流路由", "直接汇报"),
        (template_tid, "⚙️ 执行模板", "grid", "适用工作流路由", "直接执行"),
        (template_tid, "🗂 模板看板", "kanban", None, None),
        # v8.6.19 — 甘特视图（用户首次打开 UI 选「创建时间→完成日期」做时间轴）
        (task_tid, "📅 任务甘特", "gantt", None, None),
        # v8.6.19 — 表单视图（创建后调 _share_form_view 拿 shared_url）
        (task_tid, "📥 需求收集表", "form", None, None),
    ]
    created_views: list[dict[str, str]] = []
    form_views: list[dict[str, str]] = []
    for table_id, name, vtype, filter_field, filter_value in view_plan:
        try:
            view_id = await create_view(
                app_token, table_id, name, vtype,
                filter_field=filter_field, filter_value=filter_value,
            )
            view_meta = {
                "table_id": table_id,
                "view_name": name,
                "view_type": vtype,
                "view_id": view_id or "",
            }
            # v8.6.19 — form 视图建好后尽力共享，得到 shared_url
            # v8.6.20-r8（审计 #6）：表单视图不论 share 是否成功都要进 form_views，
            # 让下游 _build_native_assets 能拿到 view_id 关联到「需求收集表」蓝图。
            # 之前 share 失败 → form_views 空 → form_blueprints[0].view_id="" → 用户
            # 即使到飞书 UI 手动开启共享，cockpit 也找不到该视图链接。
            if vtype == "form" and view_id:
                shared_url = await _share_form_view(app_token, table_id, view_id)
                if shared_url:
                    view_meta["shared_url"] = shared_url
                    logger.info("Form view %r shared at %s", name, redact_sensitive_text(shared_url))
                form_views.append(view_meta)
            created_views.append(view_meta)
        except Exception as exc:
            logger.warning(
                "创建视图失败 table=%s name=%s: %s",
                table_id,
                name,
                redact_sensitive_text(exc, max_chars=500),
            )
    return {"views": created_views, "forms": form_views}


def _build_native_assets(
    *,
    app_token: str,
    base_url: str,
    table_ids: dict,
    view_assets: dict,
    base_meta: dict,
) -> dict:
    task_tid = table_ids["task"]
    template_tid = table_ids["template"]
    automation_specs = build_automation_specs()
    workflow_specs = build_workflow_specs()
    dashboard_specs = build_dashboard_specs()
    role_specs = build_role_specs()
    form_spec = build_form_spec()
    advperm_blueprints = [
        {
            "name": "Base 高级权限",
            "status": "blueprint_ready",
            "lifecycle_state": "blueprint_ready",
            "native_surface": "advperm",
            "delivery_mode": "manual_native_config",
            "api_readiness": "not_connected",
            "next_step": "先启用 Base 高级权限，再继续创建角色与角色工作面。",
            "blocking_reason": "当前仍需 Base 管理员权限启用高级权限。",
        }
    ]
    task_forms = view_assets.get("forms") or []
    intake_form = next((item for item in task_forms if item.get("view_name") == "📥 需求收集表"), None)
    form_blueprints = [
        {
            "name": "任务收集表单",
            "status": "ready" if intake_form and intake_form.get("shared_url") else "manual_share_required",
            "lifecycle_state": "created" if intake_form and intake_form.get("shared_url") else "manual_finish_required",
            "native_surface": "form",
            "delivery_mode": "setup_created_view",
            "api_readiness": "connected",
            "next_step": "直接把共享链接发给业务方收集新任务" if intake_form and intake_form.get("shared_url") else "在飞书 UI 中开启表单共享，拿到可直接投递的链接",
            "blocking_reason": "" if intake_form and intake_form.get("shared_url") else "表单视图已创建，但共享链接仍需在飞书内确认或开启",
            "table_id": task_tid,
            "view_id": (intake_form or {}).get("view_id", ""),
            "shared_url": (intake_form or {}).get("shared_url", ""),
            "entry_fields": [str(question["title"]) for question in form_spec["questions"]],
            "question_count": len(form_spec["questions"]),
            "questions": form_spec["questions"],
            "description": form_spec["description"],
        }
    ]
    automation_templates = [
        {
            "name": spec["name"],
            "lifecycle_state": "blueprint_ready",
            "native_surface": "automation",
            "delivery_mode": "manual_native_config",
            "api_readiness": "not_connected",
            "next_step": "直接用命令包创建后，再在飞书里补齐真实成员、审批链和任务动作",
            "blocking_reason": "当前仍需真实租户权限才能把自动化 scaffold 创建到飞书云侧",
            "trigger": spec["trigger"],
            "condition": spec["condition"],
            "action": spec["action"],
            "primary_field": spec["primary_field"],
            "summary": spec["summary"],
            "receiver_binding_fields": spec.get("receiver_binding_fields", []),
            "owner_binding_fields": spec.get("owner_binding_fields", []),
            "requires_member_binding": bool(spec.get("requires_member_binding")),
        }
        for spec in automation_specs
    ]
    workflow_blueprints = [
        {
            "name": spec["name"],
            "status": "blueprint_ready",
            "lifecycle_state": "blueprint_ready",
            "native_surface": "workflow",
            "delivery_mode": "manual_native_config",
            "api_readiness": "not_connected",
            "next_step": "先创建工作流 scaffold，再在飞书里补齐成员映射和审批/任务动作",
            "blocking_reason": "当前仓库已经给出可创建 JSON，但真实落地仍依赖飞书租户权限",
            "entry_condition": spec["entry_condition"],
            "route_field": spec["route_field"],
            "actions": spec["actions"],
            "summary": spec["summary"],
            "receiver_binding_fields": spec.get("receiver_binding_fields", []),
            "requires_member_binding": bool(spec.get("requires_member_binding")),
        }
        for spec in workflow_specs
    ]
    dashboard_blueprints = [
        {
            "name": spec["name"],
            "status": "blueprint_ready",
            "lifecycle_state": "blueprint_ready",
            "native_surface": "dashboard",
            "delivery_mode": "manual_native_config",
            "api_readiness": "not_connected",
            "next_step": "按 block 顺序创建后，再用飞书原生布局做管理层汇报排版",
            "blocking_reason": "当前仓库提供的是可执行图表蓝图，真正云侧创建仍依赖权限与配额",
            "source_table": table_ids["task"] if spec["source_table_name"] == "分析任务" else table_ids.get("evidence", task_tid),
            "focus_metrics": spec["focus_metrics"],
            "recommended_views": spec["recommended_views"],
            "narrative": spec["narrative"],
            "block_count": len(spec["block_specs"]),
        }
        for spec in dashboard_specs
    ]
    role_blueprints = [
        {
            "name": spec["name"],
            "status": "blueprint_ready",
            "lifecycle_state": "blueprint_ready",
            "native_surface": "role",
            "delivery_mode": "manual_native_config",
            "api_readiness": "not_connected",
            "next_step": "直接创建角色后再分配真实成员，不需要从零编权限 JSON",
            "blocking_reason": "当前仍需 Base 管理员权限启用高级权限并创建角色",
            "focus_views": spec["focus_views"],
            "permissions_focus": spec["permissions_focus"],
            "dashboard_focus": spec["dashboard_focus"],
        }
        for spec in role_specs
    ]
    asset_groups = [
        {"key": "advperm", "label": "高级权限", "items": advperm_blueprints},
        {"key": "forms", "label": "表单入口", "items": form_blueprints},
        {"key": "automations", "label": "自动化模板", "items": automation_templates},
        {"key": "workflows", "label": "工作流蓝图", "items": workflow_blueprints},
        {"key": "dashboards", "label": "仪表盘蓝图", "items": dashboard_blueprints},
        {"key": "roles", "label": "角色蓝图", "items": role_blueprints},
    ]
    status_summary = _summarize_native_asset_states(asset_groups)
    return {
        "advperm_state": "blueprint_ready",
        "status": status_summary["overall_state"],
        "overall_state": status_summary["overall_state"],
        "state_descriptions": NATIVE_ASSET_STATES,
        "status_summary": status_summary,
        "asset_groups": status_summary["groups"],
        "base_meta": base_meta,
        "base_url": base_url,
        "app_token": app_token,
        "advperm_blueprints": advperm_blueprints,
        "form_blueprints": form_blueprints,
        "automation_templates": automation_templates,
        "workflow_blueprints": workflow_blueprints,
        "dashboard_blueprints": dashboard_blueprints,
        "role_blueprints": role_blueprints,
        "manual_finish_checklist": _build_manual_finish_checklist(
            task_tid=task_tid,
            table_ids=table_ids,
            advperm_state="blueprint_ready",
            form_blueprints=form_blueprints,
            automation_templates=automation_templates,
            workflow_blueprints=workflow_blueprints,
            dashboard_blueprints=dashboard_blueprints,
            role_blueprints=role_blueprints,
        ),
        "template_center_table_id": template_tid,
    }


def _summarize_native_asset_states(asset_groups: list[dict]) -> dict:
    priority = {
        "permission_blocked": 5,
        "manual_finish_required": 4,
        "blueprint_ready": 3,
        "api_supported": 2,
        "created": 1,
    }
    counts: dict[str, int] = {key: 0 for key in NATIVE_ASSET_STATES}
    groups: list[dict[str, object]] = []
    overall_state = "created"

    for group in asset_groups:
        items = group.get("items") or []
        group_counts: dict[str, int] = {key: 0 for key in NATIVE_ASSET_STATES}
        group_state = "created"
        for item in items:
            state = str((item or {}).get("lifecycle_state") or "blueprint_ready")
            if state not in counts:
                state = "blueprint_ready"
            counts[state] += 1
            group_counts[state] += 1
            if priority[state] > priority[group_state]:
                group_state = state
            if priority[state] > priority[overall_state]:
                overall_state = state
        groups.append(
            {
                "key": group.get("key", ""),
                "label": group.get("label", ""),
                "count": len(items),
                "state": group_state,
                "counts": group_counts,
            }
        )

    return {
        "overall_state": overall_state,
        "counts": counts,
        "total_assets": sum(counts.values()),
        "groups": groups,
    }


def _build_manual_finish_checklist(
    *,
    task_tid: str,
    table_ids: dict,
    advperm_state: str,
    form_blueprints: list[dict],
    automation_templates: list[dict],
    workflow_blueprints: list[dict],
    dashboard_blueprints: list[dict],
    role_blueprints: list[dict],
) -> list[dict[str, object]]:
    intake_form = form_blueprints[0] if form_blueprints else {}
    return [
        {
            "name": "启用 Base 高级权限",
            "surface": "高级权限",
            "state": advperm_state,
            "done": advperm_state == "created",
            "owner": "Base 管理员",
            "target_table": task_tid,
            "step": "先启用 Base 高级权限，再继续创建自定义角色和分角色工作面。",
        },
        {
            "name": "开放任务收集表单",
            "surface": "表单",
            "state": str(intake_form.get("lifecycle_state") or "manual_finish_required"),
            "done": bool(intake_form.get("shared_url")),
            "owner": "Base 管理员",
            "target_table": task_tid,
            "step": "在 `分析任务 -> 📥 需求收集表` 开启共享，拿到可直接投递的新任务入口。",
        },
        {
            "name": "配置主表自动化模板",
            "surface": "自动化",
            "state": "blueprint_ready",
            "done": False,
            "owner": "交付运营",
            "target_table": task_tid,
            "step": f"按蓝图把 {len(automation_templates)} 条自动化配置到 `分析任务` 主表，打通消息、任务、复核提醒。",
        },
        {
            "name": "创建路由工作流",
            "surface": "工作流",
            "state": "blueprint_ready",
            "done": False,
            "owner": "流程管理员",
            "target_table": task_tid,
            "step": f"按蓝图把 {len(workflow_blueprints)} 条路由工作流落到飞书工作流中心，承接拍板、执行、复核分支。",
        },
        {
            "name": "搭建管理仪表盘",
            "surface": "仪表盘",
            "state": "blueprint_ready",
            "done": False,
            "owner": "汇报负责人",
            "target_table": table_ids.get("report", ""),
            "step": f"用 {len(dashboard_blueprints)} 份仪表盘蓝图把管理总览、证据评审、异常雷达做成飞书原生看板。",
        },
        {
            "name": "按角色配置高级权限",
            "surface": "角色权限",
            "state": "blueprint_ready",
            "done": False,
            "owner": "系统管理员",
            "target_table": task_tid,
            "step": f"根据 {len(role_blueprints)} 份角色蓝图配置高管、执行、复核工作面，收敛非必要视图暴露。",
        },
    ]


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
                    f"list fields failed: status={r.status_code} code={body.get('code')} "
                    f"msg={redact_sensitive_text(body.get('msg'), max_chars=500)}"
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
                    f"status={r.status_code} code={body.get('code')} "
                    f"msg={redact_sensitive_text(body.get('msg'), max_chars=500)}"
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
        logger.warning("综合评分 公式字段创建失败 (non-fatal): %s", redact_sensitive_text(exc, max_chars=500))
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
        logger.warning("健康度数值 公式字段创建失败 (non-fatal): %s", redact_sensitive_text(exc, max_chars=500))
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
                    r.status_code, body.get("code"), redact_sensitive_text(body.get("msg"), max_chars=500),
                )
                return None
            # 部分接口在 PATCH 响应里就有 shared_url，部分需要再 GET
            form_data = (body.get("data") or {}).get("form") or {}
            shared_url = form_data.get("shared_url")
            if shared_url:
                return shared_url
            r2 = await h.get(url, headers={"Authorization": f"Bearer {token}"})
            body2 = _safe_json(r2)
            # v8.6.20-r8（审计 #5）：之前不检查第二 GET 的 status / code / shared 标志
            # 就直接拿 .shared_url，会把飞书错误响应里的 expired/error URL 误当成有效
            # 共享地址回写到 manifest，下游用户点开看到 404。
            if r2.status_code != 200 or body2.get("code") != 0:
                logger.warning(
                    "GET form metadata after share failed: status=%s code=%s msg=%s",
                    r2.status_code, body2.get("code"), redact_sensitive_text(body2.get("msg"), max_chars=500),
                )
                return None
            form_data = (body2.get("data") or {}).get("form") or {}
            if not form_data.get("shared"):
                logger.warning("GET form metadata returned shared=false; share may not have taken effect")
                return None
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
    tenant_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> None:
    """
    持续运行七岗多智能体调度循环。

    每轮调用 run_one_cycle()，对所有「待分析」任务执行完整的七岗 DAG 流水线：
    Wave1（5个并行Agent）→ Wave2（财务顾问）→ Wave3（CEO助理综合）

    v8.6.20-r14（审计 #2）：tenant_id / correlation_id 由调用方 snapshot 传入，
    在 loop 内重建 ContextVar 作用域；否则 record_usage / record_audit / cache
    都跑到 tenant="default" 桶，多租户隔离破坏。
    """
    from app.core.observability import correlation_scope, set_task_context
    global _running, _stop_event
    with _state_lock:
        _running = True  # belt-and-suspenders; mark_starting() already set this
    _stop_event = asyncio.Event()
    cycle = 0
    logger.info("Workflow loop started (interval=%ds tenant=%s)", interval, tenant_id or "-")

    async with correlation_scope(correlation_id):
        if tenant_id:
            set_task_context(tenant_id=tenant_id)
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
