"""Prompt injection 防护 — 检测并消毒用户提供的输入数据。

适用对象：
  - <user_task>         任务描述
  - <data_input>        粘贴的 CSV/文本数据
  - <upstream_analysis> 上游 agent 输出（一般可信但仍走一遍）
  - <feishu_context>    飞书 OAuth 拉取的文档/任务/日历

策略：
  1. 检测高风险关键词（中英常见 jailbreak 模式）
  2. 把检测到的可疑片段用 [REDACTED:reason] 替代，保留上下文
  3. 检测到攻击时通过 logger.warning 打告警事件，便于审计
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# 高风险模式（小写匹配，覆盖中英常见越狱）
_INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ignore_previous", re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|rules?)", re.IGNORECASE)),
    ("disregard_system", re.compile(r"disregard\s+(?:the\s+)?system\s+(?:prompt|message)", re.IGNORECASE)),
    ("you_are_now", re.compile(r"you\s+are\s+(?:now|actually)\s+(?:a|an)\s+\w+", re.IGNORECASE)),
    ("act_as_jailbreak", re.compile(r"act\s+as\s+(?:dan|sudo|admin|developer)", re.IGNORECASE)),
    ("forget_instructions", re.compile(r"forget\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions?|context)", re.IGNORECASE)),
    ("system_prompt_leak", re.compile(r"(?:reveal|show|print|leak)\s+(?:the\s+)?system\s+(?:prompt|message|instruction)", re.IGNORECASE)),
    ("zh_ignore", re.compile(r"忽略\s*(?:以上|上述|之前|前面)\s*(?:所有)?\s*(?:指令|提示|规则)")),
    ("zh_forget", re.compile(r"忘记\s*(?:之前|以上|所有)\s*(?:的)?\s*(?:指令|对话|提示)")),
    ("zh_role_change", re.compile(r"(?:你现在|从现在开始)\s*是\s*(?:一个|一名)?\s*[^\s]{1,20}(?:开发者|管理员|root|sudo)")),
    ("xml_break", re.compile(r"</\s*(?:user_task|data_input|upstream_analysis|feishu_context|long_term_memory|previous_analysis|question|user_instructions|system|instruction)\s*>", re.IGNORECASE)),
    ("control_chars", re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+")),
]


@dataclass
class GuardResult:
    text: str               # 消毒后的文本
    redactions: list[str]   # 命中的模式名列表
    injection_detected: bool


def sanitize(text: str, *, source: str = "unknown") -> GuardResult:
    """检测 + 消毒。命中的片段以 [REDACTED:pattern] 替换。"""
    if not text:
        return GuardResult(text="", redactions=[], injection_detected=False)

    sanitized = text
    hits: list[str] = []
    for pattern_name, pattern in _INJECTION_PATTERNS:
        matches = list(pattern.finditer(sanitized))
        if not matches:
            continue
        hits.append(pattern_name)
        # 从后往前替换，避免 offset 偏移
        for m in reversed(matches):
            sanitized = sanitized[: m.start()] + f"[REDACTED:{pattern_name}]" + sanitized[m.end() :]

    if hits:
        logger.warning(
            "prompt_injection.detected",
            extra={"source": source, "patterns": hits, "sample": text[:200]},
        )
    return GuardResult(text=sanitized, redactions=hits, injection_detected=bool(hits))


def is_suspicious(text: str) -> bool:
    """快速判断（不消毒）— 用于审计/统计场景。"""
    if not text:
        return False
    return any(p.search(text) for _, p in _INJECTION_PATTERNS)
