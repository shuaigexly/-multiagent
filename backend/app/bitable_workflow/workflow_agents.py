"""
内容运营虚拟组织 — 三个 AI 数字员工

EditorAgent    内容编辑：读取「待选题」任务，撰写草稿，写回多维表格
ReviewerAgent  内容审核员：读取「待审核」任务，评审质量，更新审核结果
AnalystAgent   运营分析师：汇总发布数据，生成周报写入报告表
"""
import logging
import re
from datetime import datetime
from typing import Optional

from app.bitable_workflow import bitable_ops
from app.bitable_workflow.schema import Status
from app.core.llm_client import call_llm

logger = logging.getLogger(__name__)

_EDITOR_SYSTEM = (
    "你是一名专业内容编辑。根据给定的标题和内容类型，撰写一篇200-400字的高质量内容草稿。"
    "要求：观点鲜明、数据支撑、逻辑清晰、有实操价值。"
    "结尾以「要点：」列出3条核心观点。"
)

_REVIEWER_SYSTEM = (
    "你是内容质量审核员。评审内容草稿，输出固定格式：\n"
    "结论：通过 或 拒绝\n"
    "评分：<1-10整数>\n"
    "意见：<审核要点，50字以内>"
)

_ANALYST_SYSTEM = (
    "你是运营数据分析师。根据提供的内容产出统计数据，生成运营周报。"
    "输出格式：\n"
    "## 本期摘要\n<2-3句话总结>\n"
    "## 关键指标\n<指标列表，每行一个>\n"
    "## 改进建议\n<3条可操作建议>"
)


class EditorAgent:
    agent_id = "editor"
    agent_name = "内容编辑"

    async def process(
        self, app_token: str, table_id: str, record: dict,
        performance_table_id: Optional[str] = None,
    ) -> None:
        record_id = record["record_id"]
        fields = record.get("fields", {})
        title = fields.get("标题", "未命名")
        content_type = fields.get("内容类型", "行业洞察")

        draft = await call_llm(
            system_prompt=_EDITOR_SYSTEM,
            user_prompt=f"标题：{title}\n内容类型：{content_type}\n请撰写草稿。",
            temperature=0.7,
            max_tokens=800,
        )

        await bitable_ops.update_record(
            app_token, table_id, record_id,
            {
                "状态": Status.PENDING_REVIEW,
                "草稿内容": draft[:2000],
            },
        )
        if performance_table_id:
            await update_agent_performance(app_token, performance_table_id, self.agent_name, "内容编辑")
        logger.info("Editor: [%s] → 待审核", title)


class ReviewerAgent:
    agent_id = "reviewer"
    agent_name = "内容审核员"

    async def process(
        self, app_token: str, table_id: str, record: dict,
        performance_table_id: Optional[str] = None,
    ) -> None:
        record_id = record["record_id"]
        fields = record.get("fields", {})
        title = fields.get("标题", "未命名")
        draft = fields.get("草稿内容", "")

        verdict = await call_llm(
            system_prompt=_REVIEWER_SYSTEM,
            user_prompt=f"标题：{title}\n\n草稿：\n{draft[:1500]}",
            temperature=0.2,
            max_tokens=200,
        )

        conclusion_line = next((l for l in verdict.splitlines() if "结论" in l), verdict[:50])
        approved = "通过" in conclusion_line and "拒绝" not in conclusion_line
        score = _extract_score(verdict)
        new_status = Status.PUBLISHED if approved else Status.REJECTED

        update_fields: dict = {
            "状态": new_status,
            "审核意见": verdict[:500],
        }
        if score is not None:
            update_fields["质量评分"] = score
        if approved:
            update_fields["发布时间"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        await bitable_ops.update_record(app_token, table_id, record_id, update_fields)
        if performance_table_id:
            await update_agent_performance(
                app_token, performance_table_id, self.agent_name, "内容审核员",
                score=score, passed=approved,
            )
        logger.info("Reviewer: [%s] → %s (score=%s)", title, new_status, score)


class AnalystAgent:
    agent_id = "analyst"
    agent_name = "运营分析师"

    async def analyze(
        self,
        app_token: str,
        content_table_id: str,
        report_table_id: str,
        period: Optional[str] = None,
    ) -> str:
        period = period or datetime.now().strftime("%Y-%m-%d")
        records = await bitable_ops.list_records(app_token, content_table_id, page_size=100)

        # 仅统计本周期未归档记录（PUBLISHED 和 REJECTED），已标记 ANALYZED 的属于历史批次
        published = [r for r in records if r.get("fields", {}).get("状态") == Status.PUBLISHED]
        rejected = [r for r in records if r.get("fields", {}).get("状态") == Status.REJECTED]
        total = len(published) + len(rejected)

        if total == 0:
            logger.info("Analyst: no new records in period=%s, skipping report", period)
            return ""

        approve_rate = round(len(published) / total * 100, 1)
        scores = [
            float(r["fields"]["质量评分"])
            for r in published
            if isinstance(r.get("fields", {}).get("质量评分"), (int, float))
        ]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0

        data_summary = (
            f"统计周期：{period}\n"
            f"总任务数：{total}，已发布：{len(published)}，"
            f"通过率：{approve_rate}%，平均质量分：{avg_score}"
        )

        report_raw = await call_llm(
            system_prompt=_ANALYST_SYSTEM,
            user_prompt=data_summary,
            temperature=0.4,
            max_tokens=600,
        )

        record_id = await bitable_ops.create_record(
            app_token, report_table_id,
            {
                "报告周期": period,
                "总产出": total,
                "通过率": approve_rate,
                "摘要": data_summary,
                "关键指标": f"发布{len(published)}篇；平均质量分{avg_score}；通过率{approve_rate}%",
                "改进建议": report_raw[:1000],
                "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
        )

        # Archive both published and rejected so they don't re-enter the next period's count
        for r in published + rejected:
            await bitable_ops.update_record(
                app_token, content_table_id, r["record_id"],
                {"状态": Status.ANALYZED},
            )

        logger.info("Analyst: report created record_id=%s period=%s", record_id, period)
        return report_raw


def _extract_score(text: str) -> Optional[float]:
    m = re.search(r"评分[：:]\s*([0-9]+(?:\.[0-9]+)?)", text)
    if m:
        try:
            score = float(m.group(1))
            return max(1.0, min(10.0, score))
        except ValueError:
            pass
    return None


async def update_agent_performance(
    app_token: str,
    performance_table_id: str,
    agent_name: str,
    role: str,
    tasks_delta: int = 1,
    score: Optional[float] = None,
    passed: Optional[bool] = None,
) -> None:
    """在员工效能表中更新员工处理量、平均质量分、通过率。"""
    existing = await bitable_ops.list_records(
        app_token,
        performance_table_id,
        filter_expr=f'CurrentValue.[员工姓名]="{agent_name}"',
    )
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    if existing:
        record = existing[0]
        rid = record["record_id"]
        fields = record.get("fields", {})
        prev_count = float(fields.get("处理任务数", 0) or 0)
        prev_avg = float(fields.get("平均质量分", 0.0) or 0.0)
        prev_pass_rate = float(fields.get("通过率", 0.0) or 0.0)
        prev_scored = float(fields.get("已评分任务数", 0) or 0)
        new_count = prev_count + tasks_delta

        # Rolling avg uses scored-task count as denominator, not total task count,
        # so unscored tasks don't dilute the average.
        if score is not None:
            new_scored = prev_scored + 1
            new_avg = round((prev_avg * prev_scored + score) / new_scored, 1)
        else:
            new_scored = prev_scored
            new_avg = prev_avg

        # 滚动通过率（仅审核员有 passed 时更新）
        if passed is not None and new_count > 0:
            prev_approved = round(prev_pass_rate * prev_count / 100)
            new_approved = prev_approved + (1 if passed else 0)
            new_pass_rate = round(new_approved / new_count * 100, 1)
        else:
            new_pass_rate = prev_pass_rate

        await bitable_ops.update_record(
            app_token, performance_table_id, rid,
            {
                "处理任务数": new_count,
                "平均质量分": new_avg,
                "已评分任务数": new_scored,
                "通过率": new_pass_rate,
                "更新时间": now_str,
            },
        )
    else:
        initial_pass_rate = 100.0 if passed is True else (0.0 if passed is False else 0.0)
        await bitable_ops.create_record(
            app_token, performance_table_id,
            {
                "员工姓名": agent_name,
                "角色": role,
                "处理任务数": float(tasks_delta),
                "通过率": initial_pass_rate,
                "平均质量分": score if score is not None else 0.0,
                "已评分任务数": 1.0 if score is not None else 0.0,
                "更新时间": now_str,
            },
        )
