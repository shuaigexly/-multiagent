"""
内容运营虚拟组织 — 七岗多智能体协作流水线

复用 app.agents 注册的七个 BaseAgent，按 AGENT_DEPENDENCIES DAG 组织执行：

  Wave 1（并行，无上游依赖）
    DataAnalystAgent      数据分析师  — 指标分析、趋势洞察
    ContentManagerAgent   内容负责人  — 内容资产盘点、创作策略
    SEOAdvisorAgent       SEO增长顾问 — 关键词机会、流量增长
    ProductManagerAgent   产品经理    — 需求分析、路线图规划
    OperationsManagerAgent 运营负责人 — 执行规划、任务拆解

  Wave 2（依赖数据分析师输出）
    FinanceAdvisorAgent   财务顾问    — 收支诊断、现金流分析

  Wave 3（汇总所有上游）
    CEOAssistantAgent     CEO 助理    — 综合管理决策摘要
"""
import asyncio
import hashlib
import json as _json
import logging
from datetime import datetime
from typing import Optional

from app.agents.base_agent import AgentResult, ResultSection
from app.agents.ceo_assistant import ceo_assistant_agent
from app.agents.content_manager import content_manager_agent
from app.agents.data_analyst import data_analyst_agent
from app.agents.finance_advisor import finance_advisor_agent
from app.agents.operations_manager import operations_manager_agent
from app.agents.product_manager import product_manager_agent
from app.agents.seo_advisor import seo_advisor_agent
from app.bitable_workflow import bitable_ops
from app.core.text_utils import truncate_with_marker

logger = logging.getLogger(__name__)

# Wave 1: no upstream dependency — run in parallel
_WAVE1_AGENTS = [
    data_analyst_agent,
    content_manager_agent,
    seo_advisor_agent,
    product_manager_agent,
    operations_manager_agent,
]

# Wave 2: finance_advisor needs data_analyst output
_WAVE2_AGENTS = [finance_advisor_agent]

# Wave 3: synthesizes all upstream results
_WAVE3_AGENT = ceo_assistant_agent


def _build_task_description(fields: dict) -> str:
    title = fields.get("任务标题", "未命名任务")
    dimension = fields.get("分析维度", "综合分析")
    background = fields.get("背景说明", "")
    desc = f"任务：{title}\n分析维度：{dimension}"
    if background:
        desc += f"\n背景说明：{background}"
    return desc


def _error_result(agent_id: str, agent_name: str, exc: Exception) -> AgentResult:
    return AgentResult(
        agent_id=agent_id,
        agent_name=agent_name,
        sections=[ResultSection(title="错误", content=f"分析失败：{exc}")],
        action_items=[],
        raw_output=f"FAILED: {exc}",
        chart_data=[],
    )


def _is_failed_result(result: AgentResult) -> bool:
    return (result.raw_output or "").startswith("FAILED:")


def _raise_if_failed(results: list[AgentResult], stage: str) -> None:
    failed = [r for r in results if _is_failed_result(r)]
    if failed:
        names = ", ".join(r.agent_name for r in failed)
        raise RuntimeError(f"{stage} failed agents: {names}")


def _cache_input_hash(task_description: str, data_summary, upstream: Optional[list[AgentResult]]) -> str:
    data_payload = data_summary.model_dump() if hasattr(data_summary, "model_dump") else None
    upstream_payload = [
        {
            "agent_id": r.agent_id,
            "raw_output": r.raw_output,
            "actions": r.action_items,
        }
        for r in (upstream or [])
    ]
    payload = {
        "task_description": task_description,
        "data_summary": data_payload,
        "upstream": upstream_payload,
    }
    encoded = _json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


async def _safe_analyze(
    agent,
    task_description: str,
    upstream: Optional[list[AgentResult]] = None,
    data_summary=None,
    task_id: Optional[str] = None,
) -> AgentResult:
    """Run one agent with error isolation + optional Redis cache by input hash."""
    input_hash = _cache_input_hash(task_description, data_summary, upstream)
    # Cache hit path — skip LLM call if we've already run this agent for this task
    if task_id:
        try:
            from app.bitable_workflow.agent_cache import get_cached_result, set_cached_result

            cached = await get_cached_result(task_id, agent.agent_id, input_hash)
            if cached:
                logger.info("[cache-hit] %s/%s — skipping LLM call", task_id, agent.agent_id)
                return cached
        except Exception as cache_exc:
            logger.debug("agent cache read skipped: %s", cache_exc)

    try:
        result = await agent.analyze(
            task_description=task_description,
            data_summary=data_summary,
            upstream_results=upstream or [],
        )
    except Exception as exc:
        logger.error("[%s] analyze failed: %s", agent.agent_id, exc)
        return _error_result(agent.agent_id, agent.agent_name, exc)

    # Cache the successful result for crash recovery
    if task_id and not _is_failed_result(result):
        try:
            from app.bitable_workflow.agent_cache import set_cached_result

            await set_cached_result(task_id, agent.agent_id, input_hash, result)
        except Exception as cache_exc:
            logger.debug("agent cache write skipped: %s", cache_exc)

    return result


async def run_task_pipeline(
    task_fields: dict,
    progress_callback=None,
    task_id: Optional[str] = None,
) -> tuple[list[AgentResult], AgentResult]:
    """
    对单条任务执行完整的七岗多智能体分析流水线。

    波次执行顺序遵循 AGENT_DEPENDENCIES DAG：
      Wave 1 → Wave 2（财务顾问，需要数据分析师输出）→ Wave 3（CEO 助理，汇总全部）

    progress_callback: 可选的异步函数 async(stage: str)，在每个 Wave 完成后调用，
                       用于向主任务表写入「当前阶段」进度。
    task_id: 任务唯一 ID（通常传 Bitable record_id），用于 Redis 缓存 agent 输出；
             崩溃恢复时已完成的 agent 会直接从缓存读取，避免重跑昂贵的 LLM 调用。

    返回：(wave1+wave2 共六个 AgentResult, CEO 助理综合 AgentResult)
    """
    task_description = _build_task_description(task_fields)
    logger.info("Pipeline started for task: %s", task_fields.get("任务标题", "?"))

    # 解析用户粘贴的数据源（CSV / markdown / 文本），注入到每个 agent 的 data_summary
    data_summary = None
    data_source_text = (task_fields.get("数据源") or "").strip()
    if data_source_text:
        try:
            from app.core.data_parser import parse_content

            data_summary = parse_content(data_source_text)
            logger.info(
                "Data source parsed: type=%s rows=%d cols=%d",
                data_summary.content_type, data_summary.row_count, len(data_summary.columns),
            )
        except Exception as exc:
            logger.warning("Data source parse failed, falling back to no data: %s", exc)

    # Wave 1: parallel execution of 5 independent agents
    wave1_coros = [
        _safe_analyze(agent, task_description, data_summary=data_summary, task_id=task_id)
        for agent in _WAVE1_AGENTS
    ]
    wave1_results: list[AgentResult] = list(await asyncio.gather(*wave1_coros))
    _raise_if_failed(wave1_results, "Wave1")
    logger.info("Wave 1 complete: %d agents", len(wave1_results))
    if progress_callback:
        try:
            await progress_callback("Wave1 完成：数据分析 / 内容 / SEO / 产品 / 运营 五岗并行分析就绪")
        except Exception as cb_exc:
            logger.debug("progress_callback Wave1 failed: %s", cb_exc)

    # Wave 2: finance_advisor uses data_analyst output as upstream.
    # Look up by agent_id, not by list index, so reordering _WAVE1_AGENTS never silently
    # passes the wrong result to finance_advisor.
    wave1_by_id = {r.agent_id: r for r in wave1_results}
    da_result = wave1_by_id.get("data_analyst") or wave1_results[0]
    fa_result = await _safe_analyze(
        finance_advisor_agent, task_description,
        upstream=[da_result], data_summary=data_summary, task_id=task_id,
    )
    wave2_results = [fa_result]
    _raise_if_failed(wave2_results, "Wave2")
    logger.info("Wave 2 complete: finance_advisor")
    if progress_callback:
        try:
            await progress_callback("Wave2 完成：财务顾问分析就绪，正在生成 CEO 综合报告…")
        except Exception as cb_exc:
            logger.debug("progress_callback Wave2 failed: %s", cb_exc)

    # Wave 3: ceo_assistant synthesizes all upstream conclusions
    all_upstream = wave1_results + wave2_results
    if all(_is_failed_result(result) for result in all_upstream):
        raise RuntimeError("所有上游 Agent 均执行失败，任务无可用结果")

    # 把 wave1+wave2 注入 ContextVar，供 ask_peer 工具在 CEO LLM 调用中使用
    from app.agents.peer_qa import clear_peer_pool, set_peer_pool
    peer_token = set_peer_pool(all_upstream)
    try:
        ceo_result = await _safe_analyze(
            _WAVE3_AGENT, task_description,
            upstream=all_upstream, data_summary=data_summary, task_id=task_id,
        )
    finally:
        clear_peer_pool(peer_token)
    if _is_failed_result(ceo_result):
        raise RuntimeError(f"CEO 助理汇总失败: {ceo_result.raw_output}")
    logger.info("Wave 3 complete: ceo_assistant")
    if progress_callback:
        try:
            await progress_callback("Wave3 完成：CEO 助理综合报告生成完毕")
        except Exception as cb_exc:
            logger.debug("progress_callback Wave3 failed: %s", cb_exc)

    return all_upstream, ceo_result


async def cleanup_prior_task_outputs(
    app_token: str,
    task_title: str,
    output_table_id: Optional[str],
    report_table_id: Optional[str],
) -> None:
    """Deprecated unsafe cleanup path.

    Deleting old rows before replacement writes succeed can lose the last good
    results. Use collect_prior_task_output_ids() before writing, then
    cleanup_prior_task_output_ids() after all replacement writes succeed.
    """
    raise RuntimeError(
        "cleanup_prior_task_outputs is unsafe; use collect_prior_task_output_ids "
        "before writes and cleanup_prior_task_output_ids after successful writes"
    )


async def collect_prior_task_output_ids(
    app_token: str,
    task_title: str,
    output_table_id: Optional[str],
    report_table_id: Optional[str],
) -> dict[str, list[str]]:
    """Collect existing output/report record IDs so cleanup can happen after new writes succeed."""
    safe_title = bitable_ops.quote_filter_value(task_title)
    filter_expr = f"CurrentValue.[任务标题]={safe_title}"
    report_filter = f"CurrentValue.[报告标题]={safe_title}"
    prior = {"output": [], "report": []}
    if output_table_id:
        records = await bitable_ops.list_records(
            app_token,
            output_table_id,
            filter_expr=filter_expr,
            max_records=500,
        )
        prior["output"] = [r["record_id"] for r in records if r.get("record_id")]
    if report_table_id:
        records = await bitable_ops.list_records(
            app_token,
            report_table_id,
            filter_expr=report_filter,
            max_records=500,
        )
        prior["report"] = [r["record_id"] for r in records if r.get("record_id")]
    return prior


async def cleanup_prior_task_output_ids(
    app_token: str,
    output_table_id: Optional[str],
    report_table_id: Optional[str],
    prior_ids: dict[str, list[str]],
) -> None:
    """Best-effort cleanup of old rows collected before the successful replacement write."""
    cleanup_errors: list[str] = []
    for table_id, record_ids, label in [
        (output_table_id, prior_ids.get("output", []), "岗位分析"),
        (report_table_id, prior_ids.get("report", []), "综合报告"),
    ]:
        if not table_id:
            continue
        for record_id in record_ids:
            try:
                await bitable_ops.delete_record(app_token, table_id, record_id)
            except Exception as exc:
                logger.warning("Cleanup prior %s record=%s failed: %s", label, record_id, exc)
                cleanup_errors.append(f"{label}:{record_id}: {exc}")
    if cleanup_errors:
        raise RuntimeError("清理历史输出失败: " + "；".join(cleanup_errors[:3]))


_AGENT_ROLE_EMOJI_MAP = {
    "数据分析师": "📊 数据分析师",
    "内容负责人": "📝 内容负责人",
    "SEO/增长顾问": "🔍 SEO/增长顾问",
    "SEO 增长顾问": "🔍 SEO/增长顾问",
    "产品经理": "📱 产品经理",
    "运营负责人": "⚙️ 运营负责人",
    "财务顾问": "💰 财务顾问",
    "CEO 助理": "👔 CEO 助理",
    "CEO助理": "👔 CEO 助理",
}


def _role_with_emoji(agent_name: str) -> str:
    """Map bare agent name to the emoji-prefixed SingleSelect option label."""
    return _AGENT_ROLE_EMOJI_MAP.get(agent_name, agent_name)


_HEALTH_MAP = {
    "🟢": "🟢 健康",
    "🟡": "🟡 关注",
    "🔴": "🔴 预警",
    "⚪": "⚪ 数据不足",
}


def _extract_health(result: AgentResult) -> str:
    """健康度评级：优先 LLM 自报（metadata.health），否则从正文 emoji 推断。"""
    if result.health_hint:
        emoji = result.health_hint.strip()[:2] if len(result.health_hint.strip()) > 1 else result.health_hint.strip()
        for key, label in _HEALTH_MAP.items():
            if key in result.health_hint:
                return label
    text_blobs = [s.content or "" for s in result.sections]
    text_blobs.append(result.raw_output or "")
    combined = "\n".join(text_blobs)[:5000]
    if "🔴" in combined:
        return "🔴 预警"
    if "🟡" in combined:
        return "🟡 关注"
    if "🟢" in combined:
        return "🟢 健康"
    return "⚪ 数据不足"


def _estimate_confidence(result: AgentResult) -> int:
    """置信度：优先 LLM 自报（metadata.confidence），否则启发式估算。"""
    if 1 <= result.confidence_hint <= 5:
        return result.confidence_hint
    raw = result.raw_output or ""
    if not raw or "FAILED" in raw[:50]:
        return 1
    section_count = len(result.sections)
    action_count = len(result.action_items)
    has_chart = bool(result.chart_data)
    has_thinking = bool(result.thinking_process)
    score = 2
    if section_count >= 4:
        score += 1
    if action_count >= 3:
        score += 1
    if has_chart:
        score += 1
    if has_thinking and len(raw) > 1500:
        score += 1
    return min(5, max(1, score))


def _estimate_urgency(ceo_result: AgentResult) -> int:
    """决策紧急度：优先从 CEO 的 metadata.actions 提取最高优先级。"""
    if ceo_result.structured_actions:
        priority_score = {"P0": 5, "P1": 4, "P2": 3, "P3": 2}
        max_score = max(
            (priority_score.get((a.get("priority") or "").upper(), 0) for a in ceo_result.structured_actions),
            default=0,
        )
        if max_score:
            return max_score
    combined = (ceo_result.raw_output or "").lower()
    if "🔴" in ceo_result.raw_output or "紧急" in combined or "p0" in combined:
        return 5
    if "🟡" in ceo_result.raw_output or "重要" in combined:
        return 4
    if "🟢" in ceo_result.raw_output:
        return 2
    return 3


def _format_sections(result: AgentResult, max_chars: int = 2000) -> str:
    """Concatenate all sections into one markdown block, truncated to max_chars.

    Builds incrementally and stops as soon as the limit is reached, avoiding
    serialising the full output when only the first few sections fit.
    """
    if not result.sections:
        return truncate_with_marker(result.raw_output, max_chars, "\n...[已截断]")
    parts: list[str] = []
    total = 0
    for s in result.sections:
        chunk = f"## {s.title}\n{s.content or ''}"
        if total + len(chunk) + 2 > max_chars:
            remaining = max_chars - total - 20
            if remaining > 0 and parts:
                parts.append(truncate_with_marker(chunk, remaining + len("\n...[已截断]"), "\n...[已截断]"))
            elif remaining > 0:
                parts.append(truncate_with_marker(chunk, remaining + len("\n...[已截断]"), "\n...[已截断]"))
            break
        parts.append(chunk)
        total += len(chunk) + 2  # +2 for "\n\n" separator
    return "\n\n".join(parts)


async def write_agent_outputs(
    app_token: str,
    output_table_id: str,
    task_title: str,
    results: list[AgentResult],
    task_record_id: Optional[str] = None,
) -> int:
    """将各岗 AgentResult 写入「岗位分析」表。每个 Agent 写一条记录。

    task_record_id: 分析任务表中对应记录的 record_id，用于填写关联字段。
    返回成功写入的记录数。调用方必须校验是否等于结果数量。

    生成时间字段为 CreatedTime 类型，由飞书自动填充，无需手动写入。
    """
    from app.bitable_workflow.chart_renderer import render_chart_to_png, upload_chart_to_bitable

    written = 0
    for result in results:
        summary = _format_sections(result, max_chars=5000)
        action_text = (
            "\n".join(f"- {a}" for a in result.action_items[:15])
            if result.action_items
            else ""
        )
        # 自动渲染 chart_data → PNG → 上传 Bitable 附件字段
        chart_attachment_token: Optional[str] = None
        if result.chart_data:
            try:
                png = render_chart_to_png(
                    result.chart_data,
                    title=f"{result.agent_name} · 关键指标",
                )
                if png:
                    chart_attachment_token = await upload_chart_to_bitable(
                        app_token,
                        output_table_id,
                        png,
                        file_name=f"{result.agent_id}_chart.png",
                    )
            except Exception as render_exc:
                logger.warning("chart render/upload failed for %s: %s", result.agent_id, render_exc)

        fields: dict = {
            "任务标题": task_title,
            "岗位角色": _role_with_emoji(result.agent_name),
            "健康度评级": _extract_health(result),
            "分析摘要": summary,
            "行动项": truncate_with_marker(action_text, 2000, "\n...[已截断]"),
            "行动项数": len(result.action_items),
            "置信度": _estimate_confidence(result),
            "分析思路": truncate_with_marker(result.thinking_process, 3000, "\n...[已截断]") if result.thinking_process else "",
            "图表数据": truncate_with_marker(_json.dumps(result.chart_data, ensure_ascii=False), 3000, "\n...[已截断]") if result.chart_data else "",
        }
        if chart_attachment_token:
            fields["图表"] = [{"file_token": chart_attachment_token}]
        if task_record_id:
            fields["关联任务"] = [{"record_id": task_record_id}]
        try:
            await bitable_ops.create_record(app_token, output_table_id, fields)
            written += 1
        except Exception as exc:
            if "LinkFieldConvFail" in str(exc) and task_record_id and "关联任务" in fields:
                raise RuntimeError("关联任务字段写入失败，请修复字段类型或权限后重试") from exc
            else:
                logger.error("Failed to write output for agent=%s: %s", result.agent_name, exc)
    return written


async def write_ceo_report(
    app_token: str,
    report_table_id: str,
    task_title: str,
    ceo_result: AgentResult,
    participant_count: int,
    task_record_id: Optional[str] = None,
) -> str:
    """将 CEO 助理综合报告写入「综合报告」表，返回 record_id。

    task_record_id: 分析任务表中对应记录的 record_id，用于填写关联字段。
    CEO 报告是核心交付物；写入失败直接抛出，由调用方决定是否失败整条任务。
    生成时间字段为 CreatedTime 类型，由飞书自动填充。
    """
    def _find_section(keyword: str) -> str:
        for s in ceo_result.sections:
            if keyword in s.title:
                return truncate_with_marker(s.content or "", 1000, "\n...[已截断]")
        return ""

    record_fields: dict = {
        "报告标题": task_title,
        "综合健康度": _extract_health(ceo_result),
        "核心结论": _find_section("核心结论"),
        "重要机会": _find_section("重要机会"),
        "重要风险": _find_section("重要风险"),
        "CEO决策事项": _find_section("CEO 需决策") or _find_section("决策"),
        "管理摘要": _find_section("管理摘要") or _find_section("一段话"),
        "参与岗位数": float(participant_count),
        "决策紧急度": _estimate_urgency(ceo_result),
    }
    if task_record_id:
        record_fields["关联任务"] = [{"record_id": task_record_id}]

    try:
        return await bitable_ops.create_record(app_token, report_table_id, record_fields)
    except Exception as exc:
        if "LinkFieldConvFail" in str(exc) and task_record_id and "关联任务" in record_fields:
            raise RuntimeError("关联任务字段写入失败，请修复字段类型或权限后重试") from exc
        raise


async def update_performance(
    app_token: str,
    performance_table_id: str,
    results: list[AgentResult],
) -> None:
    """更新数字员工效能表的处理任务数（滚动累计）。

    批量拉取全表现有记录（性能表最多 7 行），避免每个 Agent 各发一次 list_records。
    最近更新字段为 ModifiedTime 类型，由飞书自动填充。
    """
    try:
        all_rows = await bitable_ops.list_records(
            app_token, performance_table_id, max_records=50
        )
    except Exception as exc:
        logger.warning("Performance: failed to fetch existing rows: %s", exc)
        all_rows = []

    perf_by_name: dict[str, dict] = {
        row.get("fields", {}).get("员工姓名", ""): row
        for row in all_rows
    }

    for result in results:
        try:
            existing = perf_by_name.get(result.agent_name)
            if existing:
                rid = existing["record_id"]
                prev = float(existing.get("fields", {}).get("处理任务数", 0) or 0)
                new_count = prev + 1
                activity = min(5, 1 + int(new_count // 2))  # 1,2,3,4,5 递进
                await bitable_ops.update_record(
                    app_token,
                    performance_table_id,
                    rid,
                    {"处理任务数": new_count, "活跃度": activity},
                )
            else:
                await bitable_ops.create_record(
                    app_token,
                    performance_table_id,
                    {
                        "员工姓名": result.agent_name,
                        "岗位": _role_with_emoji(result.agent_name),
                        "角色": result.agent_id,
                        "处理任务数": 1.0,
                        "活跃度": 1,
                    },
                )
        except Exception as exc:
            logger.warning("Performance update failed for %s: %s", result.agent_name, exc)
