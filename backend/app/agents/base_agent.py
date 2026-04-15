"""Agent 基类：所有分析模块继承此类"""
import logging
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel

from app.core.data_parser import DataSummary
from app.core.settings import settings

logger = logging.getLogger(__name__)


class ResultSection(BaseModel):
    title: str
    content: str


class AgentResult(BaseModel):
    agent_id: str
    agent_name: str
    sections: list[ResultSection]
    action_items: list[str]
    raw_output: str


class BaseAgent(ABC):
    agent_id: str = ""
    agent_name: str = ""
    agent_description: str = ""

    SYSTEM_PROMPT: str = ""
    USER_PROMPT_TEMPLATE: str = ""

    async def analyze(
        self,
        task_description: str,
        data_summary: Optional[DataSummary] = None,
        upstream_results: Optional[list[AgentResult]] = None,
        feishu_context: Optional[dict] = None,
    ) -> AgentResult:
        prompt = self._build_prompt(task_description, data_summary, upstream_results, feishu_context)
        raw = await self._call_llm(prompt)
        return self._parse_output(raw)

    def _build_prompt(
        self,
        task_description: str,
        data_summary: Optional[DataSummary],
        upstream_results: Optional[list[AgentResult]],
        feishu_context: Optional[dict],
    ) -> str:
        data_section = ""
        if data_summary:
            data_section = f"""
数据概览：
- 类型：{data_summary.content_type}
- 行数/段落数：{data_summary.row_count}
- 列名：{', '.join(data_summary.columns) if data_summary.columns else '无'}
- 预览：
{data_summary.raw_preview[:2000]}
"""

        upstream_section = ""
        if upstream_results:
            parts = []
            for r in upstream_results:
                summary_text = "\n".join(
                    f"  [{s.title}]\n  {s.content[:500]}" for s in r.sections[:3]
                )
                parts.append(f"【{r.agent_name}的分析】\n{summary_text}")
            upstream_section = "\n\n其他角色的分析结论（供参考）：\n" + "\n\n".join(parts)

        return self.USER_PROMPT_TEMPLATE.format(
            task_description=task_description,
            data_section=data_section,
            upstream_section=upstream_section,
            feishu_context=str(feishu_context or {}),
        )

    async def _call_llm(self, user_prompt: str) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()

    def _parse_output(self, raw: str) -> AgentResult:
        """将 LLM 输出解析成结构化结果。子类可覆盖。"""
        sections = []
        action_items = []
        current_title = ""
        current_lines = []
        in_actions = False

        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("##") or line.startswith("**") and line.endswith("**"):
                # 保存上一段
                if current_title and current_lines:
                    sections.append(ResultSection(
                        title=current_title,
                        content="\n".join(current_lines).strip()
                    ))
                    current_lines = []
                title = line.lstrip("#").strip().strip("*").strip()
                if any(k in title for k in ["行动", "建议", "Action", "TODO", "下一步"]):
                    in_actions = True
                    current_title = title
                else:
                    in_actions = False
                    current_title = title
            elif in_actions and (line.startswith("-") or line.startswith("•") or
                                  (len(line) > 2 and line[0].isdigit() and line[1] in ".、")):
                action_items.append(line.lstrip("-•0123456789.、 ").strip())
            else:
                current_lines.append(line)

        if current_title and current_lines:
            sections.append(ResultSection(
                title=current_title,
                content="\n".join(current_lines).strip()
            ))

        # 如果解析失败，整体作为一个段落
        if not sections:
            sections = [ResultSection(title="分析结果", content=raw[:3000])]

        return AgentResult(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            sections=sections,
            action_items=action_items,
            raw_output=raw,
        )
