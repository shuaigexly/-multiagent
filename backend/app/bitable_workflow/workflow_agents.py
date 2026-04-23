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

    async def process(self, app_token: str, table_id: str, record: dict) -> None:
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
        logger.info("Editor: [%s] → 待审核", title)


class ReviewerAgent:
    agent_id = "reviewer"
    agent_name = "内容审核员"

    async def process(self, app_token: str, table_id: str, record: dict) -> None:
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

        approved = "通过" in verdict and not verdict.startswith("拒绝")
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

        total = len(records)
        published = [r for r in records if r.get("fields", {}).get("状态") in (Status.PUBLISHED, Status.ANALYZED)]
        approved_or_published = [
            r for r in records
            if r.get("fields", {}).get("状态") in (Status.APPROVED, Status.PUBLISHED, Status.ANALYZED)
        ]
        approve_rate = round(len(approved_or_published) / total * 100, 1) if total else 0.0
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

        for r in published:
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
            return float(m.group(1))
        except ValueError:
            pass
    return None
