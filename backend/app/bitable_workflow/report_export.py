"""任务报告 → Markdown 导出（v8.6.20-r34）。

把一条主任务在 Bitable 各表里的全部产出（任务元数据 + 7 岗输出 + CEO 综合 +
证据链 + 行动项 + 复核 + 自动化日志）按用户友好顺序拼成单个 Markdown 文档，
供前端 / API 下载。给评审 + 用户离线复盘 + 知识沉淀提供可读载体。

设计要点
========
1. **不依赖前端 mapping**：Markdown 在后端组装，避免重复 i18n 与字段名维护
2. **用 _flatten_text_value 拍平富文本**：飞书 search/get 偶尔返 `[{text:..}]`
   数组，必须先拍平再拼字符串
3. **按 关联记录ID 横向扫**：复用 list_records filter_expr 拉所有从表关联记录
4. **空字段优雅省略**：缺一个表不影响其他段落，整段缺失 → 跳过段落
5. **不写敏感字段**：app_token / 内部 ID / token 字段一律 redact
"""
from __future__ import annotations

import logging
from typing import Optional

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.scheduler import _flatten_record_fields, _flatten_text_value
from app.core.redaction import redact_sensitive_text

logger = logging.getLogger(__name__)


# 飞书 Bitable filter 表达式：CurrentValue.[关联记录ID]="recXXX"
def _filter_by_link(record_id: str) -> str:
    safe = record_id.replace('"', '\\"')
    return f'CurrentValue.[关联记录ID]="{safe}"'


def _safe_text(value: object, max_len: int = 4000) -> str:
    """拍平富文本 + 截断 + 转 string，无副作用。"""
    flat = _flatten_text_value(value)
    if flat is None:
        return ""
    text = flat if isinstance(flat, str) else str(flat)
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "\n\n…[截断 — 完整内容请到 Bitable 查看]"
    return text


def _render_field_pairs(
    fields: dict,
    keys: list[tuple[str, str]],  # [(field_name, display_label)]
) -> list[str]:
    """渲染 Markdown 字段列表：- **标签**：值（空字段省略）。"""
    out: list[str] = []
    for fname, label in keys:
        raw = fields.get(fname)
        text = _safe_text(raw, max_len=600)
        if text:
            out.append(f"- **{label}**：{text}")
    return out


async def assemble_task_markdown(
    *,
    app_token: str,
    table_ids: dict[str, str],
    record_id: str,
) -> str:
    """从 Bitable 拉一条任务的全部产出，拼成 Markdown。

    Args:
        app_token: base 标识
        table_ids: setup_workflow 返回的 {表语义名 → table_id}
        record_id: 主表 record_id

    Returns:
        Markdown 字符串。任务不存在抛 ValueError。
    """
    task_tid = table_ids.get("task")
    if not task_tid:
        raise ValueError("table_ids 缺少 task")

    task = await bitable_ops.get_record(app_token, task_tid, record_id)
    raw_fields = task.get("fields") or {}
    fields = _flatten_record_fields(raw_fields)
    if not fields:
        raise ValueError(f"record_id={record_id} 在主表中未找到字段")

    title = _safe_text(fields.get("任务标题"), max_len=200) or "（未命名任务）"
    sections: list[str] = [
        f"# {title}",
        "",
        f"> 任务 record_id：`{redact_sensitive_text(record_id, max_chars=120)}`  ",
        f"> base app_token：`{redact_sensitive_text(app_token, max_chars=120)}`  ",
        f"> 由 Puff C21 七岗多智能体协同分析自动生成。",
        "",
    ]

    # ---- 1. 任务元数据 ----
    meta_lines = _render_field_pairs(
        fields,
        [
            ("任务编号", "任务编号"),
            ("分析维度", "分析维度"),
            ("优先级", "优先级"),
            ("输出目的", "输出目的"),
            ("工作流路由", "工作流路由"),
            ("状态", "状态"),
            ("综合评分", "综合评分"),
            ("当前阶段", "当前阶段"),
            ("汇报对象", "汇报对象"),
            ("拍板负责人", "拍板负责人"),
            ("执行负责人", "执行负责人"),
            ("复核负责人", "复核负责人"),
            ("完成时间", "完成时间"),
        ],
    )
    if meta_lines:
        sections.append("## 任务元数据")
        sections.extend(meta_lines)
        sections.append("")

    bg = _safe_text(fields.get("背景说明"), max_len=2000)
    if bg:
        sections.append("## 背景说明")
        sections.append(bg)
        sections.append("")

    # ---- 2. CEO 综合报告 ----
    report_tid = table_ids.get("report")
    ceo_report_md = ""
    if report_tid:
        try:
            reports = await bitable_ops.list_records(
                app_token, report_tid, filter_expr=_filter_by_link(record_id), max_records=5
            )
            if reports:
                ceo_report_md = _render_ceo_report(reports[0])
        except Exception as exc:
            logger.warning("export: load report failed: %s", redact_sensitive_text(exc, max_chars=200))
    if ceo_report_md:
        sections.append("## CEO 综合报告")
        sections.append(ceo_report_md)
        sections.append("")

    # ---- 3. 七岗各自分析 ----
    output_tid = table_ids.get("output")
    if output_tid:
        try:
            outputs = await bitable_ops.list_records(
                app_token, output_tid, filter_expr=_filter_by_link(record_id), max_records=20
            )
        except Exception as exc:
            outputs = []
            logger.warning("export: load outputs failed: %s", redact_sensitive_text(exc, max_chars=200))
        if outputs:
            sections.append("## 七岗 Agent 分析")
            for out in outputs:
                rendered = _render_agent_output(out)
                if rendered:
                    sections.append(rendered)
                    sections.append("")

    # ---- 4. 证据链 ----
    evidence_tid = table_ids.get("evidence")
    if evidence_tid:
        try:
            evidence_rows = await bitable_ops.list_records(
                app_token, evidence_tid, filter_expr=_filter_by_link(record_id), max_records=50
            )
        except Exception as exc:
            evidence_rows = []
            logger.warning("export: load evidence failed: %s", redact_sensitive_text(exc, max_chars=200))
        if evidence_rows:
            sections.append("## 证据链")
            sections.append(_render_evidence_table(evidence_rows))
            sections.append("")

    # ---- 5. 行动项 / 交付动作 ----
    action_tid = table_ids.get("action")
    if action_tid:
        try:
            actions = await bitable_ops.list_records(
                app_token, action_tid, filter_expr=_filter_by_link(record_id), max_records=30
            )
        except Exception as exc:
            actions = []
            logger.warning("export: load actions failed: %s", redact_sensitive_text(exc, max_chars=200))
        if actions:
            sections.append("## 交付动作")
            sections.append(_render_action_table(actions))
            sections.append("")

    # ---- 6. 复核历史 ----
    review_history_tid = table_ids.get("review_history")
    if review_history_tid:
        try:
            histories = await bitable_ops.list_records(
                app_token, review_history_tid, filter_expr=_filter_by_link(record_id), max_records=20
            )
        except Exception as exc:
            histories = []
            logger.warning("export: load review history failed: %s", redact_sensitive_text(exc, max_chars=200))
        if histories:
            sections.append("## 复核历史")
            for h in histories:
                rendered = _render_review_history_entry(h)
                if rendered:
                    sections.append(rendered)

    # 末尾占位 — 让 markdown 渲染器自然换行
    sections.append("")
    sections.append("---")
    sections.append("*Generated by Puff C21 Multi-Agent Workflow*")
    sections.append("")
    return "\n".join(sections)


def _render_agent_output(record: dict) -> str:
    fields = _flatten_record_fields(record.get("fields") or {})
    agent = _safe_text(fields.get("岗位名称") or fields.get("agent_name"), max_len=80) or "未知岗位"
    health = _safe_text(fields.get("健康度评级") or fields.get("健康度"), max_len=20)
    confidence = _safe_text(fields.get("置信度"), max_len=10)
    summary = _safe_text(fields.get("分析摘要") or fields.get("核心结论"), max_len=2000)
    actions = _safe_text(fields.get("行动项") or fields.get("结构化行动项"), max_len=1500)

    lines = [f"### {agent}"]
    meta_chunks = []
    if health:
        meta_chunks.append(f"健康度 {health}")
    if confidence:
        meta_chunks.append(f"置信度 {confidence}")
    if meta_chunks:
        lines.append(f"_{' · '.join(meta_chunks)}_")
        lines.append("")
    if summary:
        lines.append(summary)
    if actions:
        lines.append("")
        lines.append("**行动项**")
        lines.append(actions)
    return "\n".join(lines).strip()


def _render_ceo_report(record: dict) -> str:
    fields = _flatten_record_fields(record.get("fields") or {})
    title = _safe_text(fields.get("报告标题"), max_len=200)
    health = _safe_text(fields.get("综合健康度"), max_len=20)
    urgency = _safe_text(fields.get("决策紧急度"), max_len=10)
    summary = _safe_text(fields.get("决策摘要") or fields.get("核心结论"), max_len=4000)
    options = _safe_text(fields.get("A/B 选项") or fields.get("决策选项"), max_len=2000)

    lines: list[str] = []
    if title:
        lines.append(f"### {title}")
    meta_chunks: list[str] = []
    if health:
        meta_chunks.append(f"综合健康度 **{health}**")
    if urgency:
        meta_chunks.append(f"决策紧急度 **{urgency}**")
    if meta_chunks:
        lines.append(" · ".join(meta_chunks))
        lines.append("")
    if summary:
        lines.append(summary)
        lines.append("")
    if options:
        lines.append("**决策选项**")
        lines.append(options)
    return "\n".join(lines).strip()


def _render_evidence_table(rows: list[dict]) -> str:
    """证据表 → Markdown 表格（| 证据标题 | 等级 | 用途 | 证据内容 |）。"""
    headers = ["证据标题", "等级", "用途", "证据内容"]
    out_lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows[:40]:
        fields = _flatten_record_fields(row.get("fields") or {})
        title = _safe_text(fields.get("证据标题"), max_len=80)
        grade = _safe_text(fields.get("证据等级"), max_len=20)
        usage = _safe_text(fields.get("证据用途"), max_len=20)
        body = _safe_text(fields.get("证据内容") or fields.get("证据描述"), max_len=300)
        body = body.replace("|", "\\|").replace("\n", "<br>")
        out_lines.append(f"| {title} | {grade} | {usage} | {body} |")
    return "\n".join(out_lines)


def _render_action_table(rows: list[dict]) -> str:
    headers = ["动作标题", "类型", "状态", "负责人", "截止"]
    out_lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows[:30]:
        fields = _flatten_record_fields(row.get("fields") or {})
        title = _safe_text(fields.get("动作标题"), max_len=80)
        atype = _safe_text(fields.get("动作类型"), max_len=20)
        status = _safe_text(fields.get("动作状态"), max_len=20)
        owner = _safe_text(fields.get("负责人") or fields.get("当前责任人"), max_len=40)
        due = _safe_text(fields.get("截止时间") or fields.get("到期时间"), max_len=40)
        out_lines.append(f"| {title} | {atype} | {status} | {owner} | {due} |")
    return "\n".join(out_lines)


def _render_review_history_entry(record: dict) -> str:
    fields = _flatten_record_fields(record.get("fields") or {})
    title = _safe_text(fields.get("复核标题"), max_len=200)
    round_n = _safe_text(fields.get("复核轮次"), max_len=10)
    recommend = _safe_text(fields.get("推荐动作"), max_len=40)
    body = _safe_text(fields.get("复核结论") or fields.get("结论"), max_len=1200)
    diff = _safe_text(fields.get("新旧结论差异"), max_len=600)
    chunks = []
    if title:
        head = f"### {title}"
        if round_n:
            head += f" · 第 {round_n} 轮"
        if recommend:
            head += f" · 推荐 {recommend}"
        chunks.append(head)
    if body:
        chunks.append(body)
    if diff:
        chunks.append(f"**差异**：{diff}")
    return "\n".join(chunks).strip()
