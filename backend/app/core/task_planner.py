"""
TaskPlanner：用 LLM 识别任务类型，推荐执行模块列表和顺序。
这不是 Agent，是路由组件。
"""
import json
import logging
import re
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

VALID_MODULES = {
    "data_analyst", "finance_advisor", "seo_advisor",
    "content_manager", "product_manager", "operations_manager", "ceo_assistant",
}
MAX_SELECTED_MODULES = 4
MAX_REASONING_CHARS = 80

PLANNER_PROMPT = """你是一位经验丰富的 AI 团队调度专家，负责根据用户任务描述，精准匹配最合适的 AI 专家模块组合。

【调度原则】
1. 分析任务的核心需求（不是表面词汇），判断需要哪种专业视角
2. 选择 2-4 个模块，避免过多冗余
3. 涉及"决策/汇总/高管汇报"的任务，必须包含 ceo_assistant（放最后，做综合）
4. 涉及"数据/指标/趋势"的任务，必须包含 data_analyst（放最前，提供数据基础）
5. reasoning 要说明为什么选这些模块，而不只是重复任务名称

【可用任务类型和专家模块】
{task_types_desc}

【用户任务】
{user_input}

请思考：
- 这个任务最核心的诉求是什么（数据分析？财务决策？内容输出？产品规划？执行落地？）
- 哪些模块的视角是必须的？哪些是锦上添花？
- 任务是否有明确的飞书输出需求（文档/任务/消息）？

只返回 JSON，不要其他任何文字：
{{
  "task_type": "<task_type_key>",
  "task_type_label": "<中文标签>",
  "selected_modules": ["<module1>", "<module2>"],
  "reasoning": "<说明选择这些模块的理由，60字以内>"
}}
"""


class TaskPlan(BaseModel):
    task_type: str
    task_type_label: str
    selected_modules: list[str]
    reasoning: str


def _normalize_selected_modules(raw_modules: object, task_type: str) -> list[str]:
    modules: list[str] = []
    if isinstance(raw_modules, list):
        for module in raw_modules:
            if module not in VALID_MODULES or module in modules:
                continue
            modules.append(module)
            if len(modules) >= MAX_SELECTED_MODULES:
                break
    return modules or list(TASK_TYPES[task_type]["modules"])


def _normalize_reasoning(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_REASONING_CHARS]


async def plan_task(user_input: str, feishu_context: Optional[dict] = None) -> TaskPlan:
    """用 LLM 识别任务类型，返回 TaskPlan。LLM 不可用时降级到关键词匹配。"""
    try:
        return await _llm_plan(user_input, feishu_context)
    except Exception as e:
        logger.warning(f"LLM planning failed, fallback to keyword matching: {e}")
        return _keyword_plan(user_input)


async def _llm_plan(user_input: str, feishu_context: Optional[dict] = None) -> TaskPlan:
    from app.core.llm_client import call_llm

    task_types_desc = "\n".join(
        f"- {k}: {v['label']} — {v['description']}"
        for k, v in TASK_TYPES.items()
    )
    context_hint = ""
    if feishu_context:
        hints = []
        if feishu_context.get("drive"):
            hints.append(f"{len(feishu_context['drive'])} 份云文档")
        if feishu_context.get("tasks"):
            pending = [t for t in feishu_context["tasks"] if not t.get("completed")]
            hints.append(f"{len(pending)} 项待办任务")
        if feishu_context.get("calendar"):
            hints.append(f"{len(feishu_context['calendar'])} 条日历事项")
        if hints:
            context_hint = f"\n\n【用户飞书数据】用户提供了：{'、'.join(hints)}，请据此优化模块选择。"
    prompt = PLANNER_PROMPT.format(
        task_types_desc=task_types_desc,
        user_input=user_input,
    ) + context_hint
    raw = await call_llm(
        system_prompt="你是一个任务分析专家，只返回 JSON，不要其他文字。",
        user_prompt=prompt,
        temperature=0,
        max_tokens=300,
    )
    raw = re.sub(r'<think(?:ing)?>.*?</think(?:ing)?>', '', raw, flags=re.DOTALL).strip()
    # 清理 markdown 代码块
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()
    data = json.loads(raw)
    task_type = data.get("task_type", "general")
    if task_type not in TASK_TYPES:
        task_type = "general"
    modules = _normalize_selected_modules(data.get("selected_modules", []), task_type)
    return TaskPlan(
        task_type=task_type,
        task_type_label=data.get("task_type_label") or TASK_TYPES[task_type]["label"],
        selected_modules=modules,
        reasoning=_normalize_reasoning(data.get("reasoning", "")),
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
