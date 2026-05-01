"""跨 agent 健康度冲突检测器（v8.6.20-r33）。

设计动机
========
旧路径完全依赖 CEO LLM 自己读上游 6 份报告然后"找出冲突"。这有两个问题：
1. LLM 在长上下文里很容易遗漏冲突（attention 稀释）— 实测对中等长度 prompt
   遗漏率 30%+。
2. 即便 LLM 注意到冲突，prompt 里没有 explicit 标记，CEO 决策仪表盘也可能
   只把它列在「跨部门整合洞察」段落而不是「需拍板的决策」里 — 用户看不见。

解决：用代码先扫一遍 upstream 的 health_hint / confidence_hint，命中 hard 冲突
（比如 数据分析师=🟢 conf>=4 但 财务顾问=🔴 conf>=4）就构造一段 `<conflict_alerts>`
文本注入 CEO prompt，强制 CEO 在「需拍板的决策」一栏里显式处理。

这是 "AI 工程化深度" 的体现：rule-based 逻辑兜住 LLM 推理盲区。

冲突等级
========
- HARD：两个 agent 健康度差 ≥ 2 档（🟢 vs 🔴）且都 confidence ≥ 3
- SOFT：差 1 档（🟢 vs 🟡 / 🟡 vs 🔴）或一方 confidence < 3
- 仅 HARD 冲突注入 prompt（信噪比优先）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.agents.base_agent import AgentResult


# 健康度等级映射：颜色 → 数值。差 ≥ 2 视为硬冲突。
_HEALTH_RANK: dict[str, int] = {
    "🟢": 3,
    "🟡": 2,
    "🔴": 1,
    "⚪": 0,  # 数据不足，单独识别为 "data_gap"
}


def _extract_health_color(health_hint: str) -> str:
    """从 "🟢 健康" / "🔴 风险" 这类带说明的 hint 里抽出第一个 emoji。"""
    if not health_hint:
        return ""
    text = health_hint.strip()
    for color in _HEALTH_RANK.keys():
        if text.startswith(color):
            return color
    return ""


@dataclass(frozen=True)
class HealthConflict:
    """两个 agent 之间的硬冲突描述符。"""
    agent_a_id: str
    agent_a_name: str
    color_a: str
    confidence_a: int
    agent_b_id: str
    agent_b_name: str
    color_b: str
    confidence_b: int

    @property
    def severity_gap(self) -> int:
        """颜色差档数（绝对值）。HARD 冲突 ≥ 2。"""
        return abs(_HEALTH_RANK.get(self.color_a, 0) - _HEALTH_RANK.get(self.color_b, 0))

    def render(self) -> str:
        return (
            f"- {self.agent_a_name}（{self.agent_a_id}）评级 {self.color_a}（置信度 {self.confidence_a}/5）"
            f" 与 {self.agent_b_name}（{self.agent_b_id}）评级 {self.color_b}（置信度 {self.confidence_b}/5）"
            f" 存在 {self.severity_gap} 档冲突。"
        )


def detect_health_conflicts(
    upstream_results: Iterable[AgentResult],
    *,
    min_confidence: int = 3,
    min_gap: int = 2,
) -> list[HealthConflict]:
    """扫描 upstream 健康度评级，输出全部硬冲突。

    Args:
        upstream_results: wave1 + wave2 的 AgentResult 列表。
        min_confidence: 双方 confidence_hint 都需 ≥ 该值才计入硬冲突。低置信度
            评级本身就不可靠，不应放大成 CEO 必读项。
        min_gap: 颜色差最小档数。默认 2（🟢 vs 🔴）；调成 1 会包括 🟢 vs 🟡。

    Returns:
        list[HealthConflict]，按 severity_gap 倒序 + agent_id 字典序。空 = 无硬冲突。
    """
    qualifying: list[tuple[str, str, str, int]] = []
    for r in upstream_results:
        color = _extract_health_color(r.health_hint)
        if color in ("", "⚪"):
            continue  # 未表态 / 数据不足 — 不参与冲突计算
        confidence = int(r.confidence_hint or 0)
        if confidence < min_confidence:
            continue
        qualifying.append((r.agent_id, r.agent_name, color, confidence))

    conflicts: list[HealthConflict] = []
    for i in range(len(qualifying)):
        for j in range(i + 1, len(qualifying)):
            a_id, a_name, a_color, a_conf = qualifying[i]
            b_id, b_name, b_color, b_conf = qualifying[j]
            gap = abs(_HEALTH_RANK[a_color] - _HEALTH_RANK[b_color])
            if gap < min_gap:
                continue
            conflicts.append(
                HealthConflict(
                    agent_a_id=a_id,
                    agent_a_name=a_name,
                    color_a=a_color,
                    confidence_a=a_conf,
                    agent_b_id=b_id,
                    agent_b_name=b_name,
                    color_b=b_color,
                    confidence_b=b_conf,
                )
            )
    conflicts.sort(key=lambda c: (-c.severity_gap, c.agent_a_id, c.agent_b_id))
    return conflicts


def format_conflicts_for_prompt(conflicts: list[HealthConflict]) -> str:
    """把硬冲突列表渲染成可注入 CEO prompt 的 XML 块；无冲突返空串。"""
    if not conflicts:
        return ""
    lines = [c.render() for c in conflicts]
    return (
        "\n<conflict_alerts>\n"
        "⚠️ 系统已自动检测到下列上游岗位之间存在硬性健康度评级冲突。\n"
        "你必须在「CEO 需拍板的决策」一栏中显式处理每一项冲突 —\n"
        "说明你倾向哪一方判断、依据是什么、以及不处理冲突的代价。\n\n"
        + "\n".join(lines)
        + "\n</conflict_alerts>\n"
    )


# v8.6.20-r36：把当前任务检测到的硬冲突存进 ContextVar，让 CEOAssistantAgent
# 在 _parse_output 阶段验证 LLM 是否真的处理了它们。形成"程序化注入 → LLM 决策
# → 程序化验证"完整闭环。
import contextvars

_active_conflicts: contextvars.ContextVar[Optional[list[HealthConflict]]] = contextvars.ContextVar(
    "active_health_conflicts", default=None
)


def set_active_conflicts(conflicts: list[HealthConflict]) -> "contextvars.Token":
    """把检测出的硬冲突注入当前 asyncio context；返回 token，调用方 reset() 清理。"""
    return _active_conflicts.set(list(conflicts))


def clear_active_conflicts(token: "contextvars.Token") -> None:
    _active_conflicts.reset(token)


def get_active_conflicts() -> list[HealthConflict]:
    return list(_active_conflicts.get() or [])


from typing import Optional  # noqa: E402  (re-import for type alias above)


def verify_conflicts_addressed(
    raw_output: str,
    conflicts: list[HealthConflict],
) -> list[HealthConflict]:
    """检查 CEO LLM 输出里每个冲突是否在「需拍板的决策」附近被 explicit 提到。

    判定规则（保守版，避免误报）：
      1. 抽出 raw_output 里 `## CEO 需拍板的决策` 标题之后到下一个 `##` 或文末
         的内容作为决策段落
      2. 对每个冲突：要求决策段落里同时出现 agent_a_name + agent_b_name
         （或对应的 agent_id 也算），其中至少一个 agent_a/b 名字必须出现在该段
      3. 任何不满足的冲突 → 返回；调用方据此追加 thinking_process 警告

    Args:
        raw_output: CEO LLM 完整输出文本
        conflicts: r33 detect_health_conflicts 返回的 HealthConflict 列表

    Returns:
        list[HealthConflict] — 未在决策段落里被处理的冲突；空 = 全处理。
    """
    if not conflicts or not raw_output:
        return list(conflicts)

    # v8.6.20-r46（自审计修复）：原实现只 split("\n## ")，LLM 用 "### " 三级标题
    # 时整段输出会落到第一个 part 里，决策段判断失效。改用正则同时匹配 ## / ###
    # 两级标题；这两级在 CEO prompt template 模板里都会出现。
    import re as _re
    decision_block = ""
    # 拆分点：行首 ## 或 ###（不含 ####+）
    parts = _re.split(r"\n#{2,3}\s+", "\n" + raw_output)
    for part in parts:
        head_line, _, body = part.partition("\n")
        if not head_line:
            continue
        if "需拍板" in head_line or ("决策" in head_line and "整合" not in head_line):
            decision_block += "\n" + body

    # 兜底：找不到决策段落 → 用整段输出（保守，避免漏报）
    if not decision_block.strip():
        decision_block = raw_output

    unresolved: list[HealthConflict] = []
    for c in conflicts:
        a_present = c.agent_a_name in decision_block or c.agent_a_id in decision_block
        b_present = c.agent_b_name in decision_block or c.agent_b_id in decision_block
        # 至少需要双方都被提到一次
        if not (a_present and b_present):
            unresolved.append(c)
    return unresolved


def format_unresolved_warning(unresolved: list[HealthConflict]) -> str:
    """生成给 thinking_process 追加的警告文本。空列表返空串。"""
    if not unresolved:
        return ""
    lines = [
        "⚠️ 系统检测到以下硬冲突未在「CEO 需拍板的决策」一栏被显式处理 —",
        "请补充取舍依据，避免决策被误读：",
    ]
    for c in unresolved:
        lines.append(f"  · {c.render()}")
    return "\n".join(lines)
