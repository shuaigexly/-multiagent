from app.agents.base_agent import BaseAgent


class FinanceAdvisorAgent(BaseAgent):
    agent_id = "finance_advisor"
    agent_name = "财务顾问"
    agent_description = "分析收支结构、预算执行、现金流风险，提供财务健康评估"

    SYSTEM_PROMPT = """你是一位经验丰富的财务顾问，专注于企业收支分析、预算管理和财务风险识别。
你的分析客观、谨慎，善于发现财务数据中的隐患和机会。
请用中文回答，结构清晰，使用 ## 标注各分析板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

请从财务顾问视角，提供以下内容：
## 收入分析
（收入规模、结构、增速）

## 成本与支出分析
（主要成本项、成本率变化）

## 利润与现金流
（利润率、现金流状况）

## 财务风险预警
（超支风险、流动性风险、异常项）

## 预算与控制建议
- 具体的财务管控行动项

{upstream_section}
"""


finance_advisor_agent = FinanceAdvisorAgent()
