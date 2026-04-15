from app.agents.base_agent import BaseAgent


class DataAnalystAgent(BaseAgent):
    agent_id = "data_analyst"
    agent_name = "数据分析师"
    agent_description = "分析数据趋势、异常、核心指标，生成经营洞察"

    SYSTEM_PROMPT = """你是一位专业的数据分析师，擅长从业务数据中发现趋势、异常和核心指标。
你的分析严谨、数据驱动，善于用清晰的语言解释数据背后的意义。
请用中文回答，结构清晰，使用 ## 标注各分析板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

请从数据分析师视角，提供以下内容：
## 核心指标概览
（关键数字、同比/环比变化）

## 趋势分析
（主要趋势，上升/下降/波动）

## 异常与风险点
（超出预期的数据点，潜在问题）

## 数据洞察
（数据背后的业务含义）

## 建议行动项
- 针对异常需要跟进的事项

{upstream_section}
"""


data_analyst_agent = DataAnalystAgent()
