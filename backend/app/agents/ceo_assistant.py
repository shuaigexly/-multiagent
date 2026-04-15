from app.agents.base_agent import BaseAgent


class CEOAssistantAgent(BaseAgent):
    agent_id = "ceo_assistant"
    agent_name = "CEO 助理"
    agent_description = "汇总所有模块结论，生成管理决策摘要"

    SYSTEM_PROMPT = """你是 CEO 的得力助理，负责汇总各部门的分析结论，生成简洁有力的管理决策摘要。
你的摘要直接、重点突出，帮助 CEO 快速掌握全局并做出决策。
请用中文回答，结构清晰，使用 ## 标注各板块。"""

    USER_PROMPT_TEMPLATE = """任务：{task_description}

{data_section}

{upstream_section}

请基于以上所有分析，生成 CEO 管理摘要：
## 本期核心结论
（3-5 条最重要的判断，每条不超过50字）

## 最大机会
（当前最值得把握的 1-2 个机会）

## 最大风险
（当前最需要警惕的 1-2 个风险）

## CEO 决策建议
（针对本期情况，建议 CEO 重点关注和推动的事项）

## 管理摘要（一段话）
（100字以内的整体评价，适合直接发群消息）
"""

    def _parse_output(self, raw: str):
        """CEO 助理特殊处理：提取"管理摘要（一段话）"作为首个 action_item"""
        result = super()._parse_output(raw)
        # 提取一段话摘要
        for section in result.sections:
            if "管理摘要" in section.title or "一段话" in section.title:
                result.action_items.insert(0, f"[摘要] {section.content.strip()}")
                break
        return result


ceo_assistant_agent = CEOAssistantAgent()
