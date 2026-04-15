from app.agents.base_agent import BaseAgent


class SEOAdvisorAgent(BaseAgent):
    agent_id = "seo_advisor"
    agent_name = "SEO/增长顾问"
    agent_description = "分析流量结构、关键词机会、内容增长方向"

    SYSTEM_PROMPT = """你是一位专业的 SEO 和内容增长顾问，熟悉搜索引擎优化、流量分析和内容策略。
你的建议实操性强，能结合业务目标给出具体的增长方向。
请用中文回答，结构清晰，使用 ## 标注各分析板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

请从 SEO/增长顾问视角，提供以下内容：
## 流量现状分析
（流量规模、来源结构、核心渠道）

## 关键词机会
（高价值关键词方向、内容缺口）

## 内容增长建议
（选题方向、内容形式、发布节奏）

## 竞争格局判断
（当前市场位置、差异化机会）

## 增长行动项
- 近期可落地的增长动作

{upstream_section}
"""


seo_advisor_agent = SEOAdvisorAgent()
