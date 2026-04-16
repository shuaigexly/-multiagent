"""
SkillLoader: 从 backend/app/skills/ 目录读取技能文件。

工作流程：
1. load_index() 解析 SKILLS.md 中的表格，得到所有技能的元数据
2. get_skills_for_agent(agent_id) 按 tags 过滤，返回匹配的技能
3. 技能内容按需懒加载并缓存，避免重复 IO
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class SkillMeta:
    skill_id: str
    file: str
    tags: list[str]  # ["all"] means every agent
    priority: str    # "high" | "normal" | "low"
    description: str

    @property
    def name(self) -> str:
        return self.description.split("：", 1)[0] if "：" in self.description else self.skill_id


@dataclass
class Skill:
    meta: SkillMeta
    content: str  # full markdown body (without frontmatter)


def _parse_skills_index() -> list[SkillMeta]:
    """Parse SKILLS.md table rows into SkillMeta objects."""
    index_path = SKILLS_DIR / "SKILLS.md"
    if not index_path.exists():
        logger.warning("SKILLS.md not found at %s", index_path)
        return []
    text = index_path.read_text(encoding="utf-8")
    skills: list[SkillMeta] = []
    # Match table rows: | skill_id | file | tags | priority | description |
    row_pattern = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
        re.MULTILINE,
    )
    for match in row_pattern.finditer(text):
        skill_id, file_, tags_str, priority, description = [m.strip() for m in match.groups()]
        # Skip header and separator rows
        if skill_id in ("skill_id", "---", "") or set(skill_id) <= {"-", " "}:
            continue
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        skills.append(SkillMeta(
            skill_id=skill_id,
            file=file_,
            tags=tags,
            priority=priority,
            description=description,
        ))
    return skills


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from markdown content."""
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            return content[end + 3:].lstrip("\n")
    return content


@lru_cache(maxsize=1)
def _get_index() -> list[SkillMeta]:
    return _parse_skills_index()


@lru_cache(maxsize=32)
def _load_skill_content(file_name: str) -> Optional[str]:
    path = SKILLS_DIR / file_name
    if not path.exists():
        logger.warning("Skill file not found: %s", path)
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        return _strip_frontmatter(raw).strip()
    except Exception as exc:
        logger.warning("Failed to read skill file %s: %s", file_name, exc)
        return None


def get_skills_for_agent(agent_id: str) -> list[Skill]:
    """
    Return loaded Skill objects whose tags match agent_id or "all".
    Sorted: high priority first.
    """
    index = _get_index()
    matched: list[SkillMeta] = [
        m for m in index
        if "all" in m.tags or agent_id in m.tags
    ]
    # Sort: high > normal > low
    _priority_order = {"high": 0, "normal": 1, "low": 2}
    matched.sort(key=lambda m: _priority_order.get(m.priority, 1))

    result: list[Skill] = []
    for meta in matched:
        content = _load_skill_content(meta.file)
        if content:
            result.append(Skill(meta=meta, content=content))
    return result


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """
    Format skill contents for injection into agent prompt.
    Returns empty string if no skills.
    """
    if not skills:
        return ""
    parts = ["<agent_skills>", "以下是本次分析适用的专业技能指南，请在分析过程中参考应用：\n"]
    for skill in skills:
        parts.append(f"### [{skill.meta.name}]\n{skill.content}\n")
    parts.append("</agent_skills>")
    return "\n".join(parts)
