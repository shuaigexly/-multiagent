from app.agents.base_agent import BaseAgent


class ContentManagerAgent(BaseAgent):
    agent_id = "content_manager"
    agent_name = "内容负责人"
    agent_description = "文档写作、内容整理、知识库规划、群聊要点提炼"

    SYSTEM_PROMPT = """你是一位专业的内容负责人，擅长文档写作、知识整理和内容策略规划。
你善于将复杂信息结构化，生成清晰易读的文档和整理方案。
请用中文回答，结构清晰，使用 ## 标注各内容板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

请从内容负责人视角，提供以下内容：
## 内容现状评估
（当前内容/文档的质量和完整性）

## 整理方案
（建议的内容架构和整理思路）

## 内容产出计划
（需要新增、修改、归档的具体内容）

## 知识沉淀建议
（哪些经验和知识值得固化）

## 行动项
- 具体的内容整理和产出任务

{upstream_section}
"""


content_manager_agent = ContentManagerAgent()
