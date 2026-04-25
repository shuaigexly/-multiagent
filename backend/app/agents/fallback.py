"""规则引擎降级链路 — LLM 全部失败时基于 upstream + agent persona 生成骨架报告。

触发：_safe_analyze 捕获 Exception 后，先尝试 build_fallback_result，再才返回 _error_result。
确保任务永不"全空 → 卡死"，至少有可读结构 + 1 个保守行动项 + confidence=1。
"""
from __future__ import annotations

import logging
from typing import Optional

from app.agents.base_agent import AgentResult, ResultSection

logger = logging.getLogger(__name__)


_AGENT_PERSONA: dict[str, dict[str, str]] = {
    "data_analyst": {
        "role": "数据分析师",
        "fallback_focus": "MAU/DAU/留存率/付费转化",
        "default_action": "本周完成核心指标看板搭建，对齐到行业基准",
    },
    "content_manager": {
        "role": "内容负责人",
        "fallback_focus": "内容资产盘点 + 创作日历",
        "default_action": "本周梳理内容结构性差距，制定 4 周创作计划",
    },
    "seo_advisor": {
        "role": "SEO/增长顾问",
        "fallback_focus": "关键词机会矩阵 + 技术 SEO",
        "default_action": "本月扫描 TOP20 关键词机会并标记可执行项",
    },
    "product_manager": {
        "role": "产品经理",
        "fallback_focus": "需求 RICE 排序 + MVP 边界",
        "default_action": "本周完成需求池 RICE 评分，输出下季度路线图",
    },
    "operations_manager": {
        "role": "运营负责人",
        "fallback_focus": "执行拆解 + RACI 协同",
        "default_action": "本周拆解关键 OKR 到具体 owner，建立周度复盘",
    },
    "finance_advisor": {
        "role": "财务顾问",
        "fallback_focus": "LTV/CAC/Burn Rate/Runway",
        "default_action": "本周完成单位经济学测算，输出 3 种情景下的现金流预测",
    },
    "ceo_assistant": {
        "role": "CEO 助理",
        "fallback_focus": "决策摘要 + A/B 选项",
        "default_action": "下周一前向管理层提交决策选项书，明确利弊与风险",
    },
}


def build_fallback_result(
    *,
    agent_id: str,
    agent_name: str,
    task_description: str,
    upstream: Optional[list[AgentResult]] = None,
    error_reason: str = "",
) -> AgentResult:
    """生成基于上游 + persona 的兜底骨架报告。"""
    persona = _AGENT_PERSONA.get(agent_id, {"role": agent_name, "fallback_focus": "—", "default_action": "本周梳理任务边界，明确数据需求"})
    role = persona["role"]
    focus = persona["fallback_focus"]
    default_action = persona["default_action"]

    upstream_summary = "（无上游分析）"
    if upstream:
        upstream_lines = []
        for r in upstream[:6]:
            head = ""
            if r.sections:
                head = (r.sections[0].content or "").strip()[:120]
            upstream_lines.append(f"- {r.agent_name}：{head or '（无内容）'}")
        upstream_summary = "\n".join(upstream_lines)

    sections = [
        ResultSection(
            title="降级说明",
            content=(
                f"⚠️ 由于 LLM 调用失败（原因：{error_reason or '未知'}），"
                f"本次「{role}」分析使用规则引擎兜底输出，仅作占位与排查参考，不可作为决策依据。"
            ),
        ),
        ResultSection(
            title=f"{role}核心关注点",
            content=(
                f"{role}在当前任务中应聚焦：{focus}。\n"
                f"任务描述：{task_description[:300]}\n\n"
                f"上游可用信息摘要：\n{upstream_summary}"
            ),
        ),
        ResultSection(
            title="下一步建议（保守版）",
            content=(
                "1) 检查 LLM 服务可达性 + 配置（API key / base url / model 名）；\n"
                "2) 重新触发本任务（已完成 agent 的输出会从缓存恢复）；\n"
                "3) 若问题持续，把降级版结果作为骨架，由人工补全数据再决策。"
            ),
        ),
    ]
    return AgentResult(
        agent_id=agent_id,
        agent_name=agent_name,
        sections=sections,
        action_items=[
            f"⚠️ {default_action}（降级输出，需人工核对）",
        ],
        raw_output=f"FALLBACK: {error_reason}",
        chart_data=[],
        thinking_process="",
        health_hint="⚪ 数据不足",
        confidence_hint=1,
        structured_actions=[
            {
                "summary": default_action,
                "priority": "P2",
                "owner": role,
                "due": "本周",
                "success_metric": "重新跑通 LLM 后正式分析覆盖此项",
            }
        ],
    )
