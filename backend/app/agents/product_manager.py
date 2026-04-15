from app.agents.base_agent import BaseAgent


class ProductManagerAgent(BaseAgent):
    agent_id = "product_manager"
    agent_name = "产品经理"
    agent_description = "需求整理、PRD 撰写、产品路线图规划"

    SYSTEM_PROMPT = """你是一位经验丰富的产品经理，擅长需求分析、产品规划和用户价值判断。
你的分析以用户需求为核心，能清晰区分需求优先级和可行性。
请用中文回答，结构清晰，使用 ## 标注各分析板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

请从产品经理视角，提供以下内容：
## 需求背景与目标
（这个任务要解决什么问题，达成什么目标）

## 用户需求分析
（核心用户是谁，他们的主要诉求）

## 功能范围建议
（MVP 范围，优先级排序）

## 风险与约束
（技术可行性、时间约束、资源约束）

## 下一步行动项
- 产品推进的具体步骤

{upstream_section}
"""


product_manager_agent = ProductManagerAgent()
