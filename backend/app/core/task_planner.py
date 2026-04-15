"""
TaskPlanner：用 LLM 识别任务类型，推荐执行模块列表和顺序。
这不是 Agent，是路由组件。
"""
import json
import logging
from typing import Optional
from pydantic import BaseModel


logger = logging.getLogger(__name__)

TASK_TYPES = {
    "business_analysis": {
        "label": "经营分析",
        "modules": ["data_analyst", "finance_advisor", "ceo_assistant"],
        "description": "分析经营数据、业绩趋势、收入成本",
    },
    "project_evaluation": {
        "label": "立项评估",
        "modules": ["product_manager", "finance_advisor", "ceo_assistant"],
        "description": "评估新项目可行性、投入产出",
    },
    "content_growth": {
        "label": "内容增长",
        "modules": ["seo_advisor", "content_manager", "operations_manager"],
        "description": "规划内容方向、SEO 关键词、增长策略",
    },
    "risk_analysis": {
        "label": "风险分析",
        "modules": ["finance_advisor", "operations_manager", "ceo_assistant"],
        "description": "识别业务风险、财务风险、运营风险",
    },
    "knowledge_organization": {
        "label": "知识整理",
        "modules": ["content_manager"],
        "description": "整理文档、知识库、内容归档",
    },
    "document_processing": {
        "label": "文档处理",
        "modules": ["content_manager"],
        "description": "修改文档、按批注调整、生成版本记录",
    },
    "calendar_analysis": {
        "label": "日历整理",
        "modules": ["data_analyst"],
        "description": "汇总时间分布、会议安排分析",
    },
    "chat_organization": {
        "label": "群聊整理",
        "modules": ["content_manager"],
        "description": "整理群聊讨论、提炼要点",
    },
    "general": {
        "label": "综合分析",
        "modules": ["data_analyst", "operations_manager", "ceo_assistant"],
        "description": "通用任务，多角度分析",
    },
}

PLANNER_PROMPT = """你是一个任务分析专家。根据用户的任务描述，判断任务类型并推荐执行模块。

可用任务类型：
{task_types_desc}

用户任务：
{user_input}

请返回 JSON 格式（只返回 JSON，不要其他文字）：
{{
  "task_type": "<task_type_key>",
  "task_type_label": "<中文标签>",
  "selected_modules": ["<module1>", "<module2>"],
  "reasoning": "<简短说明，50字以内>"
}}
"""


class TaskPlan(BaseModel):
    task_type: str
    task_type_label: str
    selected_modules: list[str]
    reasoning: str


async def plan_task(user_input: str, feishu_context: Optional[dict] = None) -> TaskPlan:
    """用 LLM 识别任务类型，返回 TaskPlan。LLM 不可用时降级到关键词匹配。"""
    try:
        return await _llm_plan(user_input)
    except Exception as e:
        logger.warning(f"LLM planning failed, fallback to keyword matching: {e}")
        return _keyword_plan(user_input)


async def _llm_plan(user_input: str) -> TaskPlan:
    from app.core.llm_client import call_llm

    task_types_desc = "\n".join(
        f"- {k}: {v['label']} — {v['description']}"
        for k, v in TASK_TYPES.items()
    )
    prompt = PLANNER_PROMPT.format(
        task_types_desc=task_types_desc,
        user_input=user_input,
    )
    raw = await call_llm(
        system_prompt="你是一个任务分析专家，只返回 JSON，不要其他文字。",
        user_prompt=prompt,
        temperature=0,
        max_tokens=300,
    )
    # 清理 markdown 代码块
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    # 校验 modules 是否合法
    valid_modules = {"data_analyst", "finance_advisor", "seo_advisor",
                     "content_manager", "product_manager", "operations_manager", "ceo_assistant"}
    modules = [m for m in data.get("selected_modules", []) if m in valid_modules]
    if not modules:
        modules = TASK_TYPES.get(data.get("task_type", "general"), TASK_TYPES["general"])["modules"]
    return TaskPlan(
        task_type=data.get("task_type", "general"),
        task_type_label=data.get("task_type_label", "综合分析"),
        selected_modules=modules,
        reasoning=data.get("reasoning", ""),
    )


def _keyword_plan(user_input: str) -> TaskPlan:
    text = user_input.lower()
    if any(k in text for k in ["经营", "业绩", "收入", "利润", "营收"]):
        key = "business_analysis"
    elif any(k in text for k in ["立项", "项目评估", "可行性"]):
        key = "project_evaluation"
    elif any(k in text for k in ["内容", "seo", "关键词", "选题", "增长"]):
        key = "content_growth"
    elif any(k in text for k in ["风险", "预警", "风控"]):
        key = "risk_analysis"
    elif any(k in text for k in ["群", "聊天", "讨论"]):
        key = "chat_organization"
    elif any(k in text for k in ["知识库", "整理", "归档"]):
        key = "knowledge_organization"
    elif any(k in text for k in ["文档", "批注", "修改"]):
        key = "document_processing"
    elif any(k in text for k in ["日历", "时间", "会议"]):
        key = "calendar_analysis"
    else:
        key = "general"
    t = TASK_TYPES[key]
    return TaskPlan(
        task_type=key,
        task_type_label=t["label"],
        selected_modules=t["modules"],
        reasoning=f"根据关键词匹配识别为{t['label']}任务",
    )
