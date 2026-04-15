"""Agent 注册表：模块 ID → Agent 实例"""
from app.agents.data_analyst import data_analyst_agent
from app.agents.finance_advisor import finance_advisor_agent
from app.agents.seo_advisor import seo_advisor_agent
from app.agents.content_manager import content_manager_agent
from app.agents.product_manager import product_manager_agent
from app.agents.operations_manager import operations_manager_agent
from app.agents.ceo_assistant import ceo_assistant_agent
from app.agents.base_agent import BaseAgent

AGENT_REGISTRY: dict[str, BaseAgent] = {
    "data_analyst": data_analyst_agent,
    "finance_advisor": finance_advisor_agent,
    "seo_advisor": seo_advisor_agent,
    "content_manager": content_manager_agent,
    "product_manager": product_manager_agent,
    "operations_manager": operations_manager_agent,
    "ceo_assistant": ceo_assistant_agent,
}

# CEO 助理总是最后执行（汇总角色）
SEQUENTIAL_LAST = {"ceo_assistant"}

# Dependency graph: agent X must complete before agents in its value set start
# Used by orchestrator for topological execution ordering
AGENT_DEPENDENCIES: dict[str, set[str]] = {
    "data_analyst": {"finance_advisor", "ceo_assistant"},
    "finance_advisor": {"ceo_assistant"},
    "product_manager": {"ceo_assistant"},
    "operations_manager": {"ceo_assistant"},
    "seo_advisor": {"ceo_assistant"},
    "content_manager": {"ceo_assistant"},
}

AGENT_INFO = [
    {
        "id": "data_analyst",
        "name": "数据分析师",
        "description": "分析数据趋势、异常、核心指标，生成经营洞察",
        "suitable_for": ["经营分析", "业绩复盘", "指标监控"],
    },
    {
        "id": "finance_advisor",
        "name": "财务顾问",
        "description": "分析收支结构、预算执行、现金流风险",
        "suitable_for": ["财务分析", "预算管理", "成本控制"],
    },
    {
        "id": "seo_advisor",
        "name": "SEO/增长顾问",
        "description": "分析流量结构、关键词机会、内容增长方向",
        "suitable_for": ["增长分析", "内容规划", "SEO 优化"],
    },
    {
        "id": "content_manager",
        "name": "内容负责人",
        "description": "文档写作、内容整理、知识库规划",
        "suitable_for": ["内容策略", "文档整理", "知识沉淀"],
    },
    {
        "id": "product_manager",
        "name": "产品经理",
        "description": "需求整理、PRD 撰写、产品路线图规划",
        "suitable_for": ["立项评估", "需求分析", "路线图规划"],
    },
    {
        "id": "operations_manager",
        "name": "运营负责人",
        "description": "行动拆解、任务分配、执行跟进",
        "suitable_for": ["行动规划", "运营问题", "任务管理"],
    },
    {
        "id": "ceo_assistant",
        "name": "CEO 助理",
        "description": "汇总所有模块结论，生成管理决策摘要",
        "suitable_for": ["综合汇总", "管理报告", "决策支持"],
    },
]
