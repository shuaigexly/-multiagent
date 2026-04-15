from app.agents.base_agent import BaseAgent


class OperationsManagerAgent(BaseAgent):
    agent_id = "operations_manager"
    agent_name = "运营负责人"
    agent_description = "行动拆解、任务分配、执行跟进、问题拆解"

    SYSTEM_PROMPT = """你是一位高效的运营负责人，擅长将战略目标拆解为可执行的行动计划。
你注重执行落地，善于识别瓶颈，推进跨团队协作。
请用中文回答，结构清晰，使用 ## 标注各分析板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

{upstream_section}

请从运营负责人视角，提供以下内容：
## 当前运营状况评估
（现在最大的运营问题是什么）

## 关键问题拆解
（将大问题拆解为具体子问题）

## 本周行动计划
（按优先级排列的具体行动）

## 资源与协作需求
（需要哪些资源或跨部门配合）

## 行动项（可转飞书任务）
- 具体行动项1（负责人/截止日期）
- 具体行动项2（负责人/截止日期）
- 具体行动项3（负责人/截止日期）
"""


operations_manager_agent = OperationsManagerAgent()
