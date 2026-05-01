"""单 agent 熔断器 — 防止持续失败的 agent 在每轮 cycle 都重试浪费 LLM 调用。

设计动机
========
真实 LLM 部署里，单一 agent 偶尔会因为模型限流 / 长尾 prompt 触发 502 / 长时
间无响应。如果调度器每轮都重试这个 agent，每条任务都被这个 broken pipe 拖
慢 1-3 分钟（等待超时），还会消耗 budget。

熔断器：跟踪每个 agent_id 的滑动窗口（默认 10 次最近调用）失败率。失败率
≥ threshold（默认 0.6）→ 进入 OPEN 状态，cool-down 期内（默认 5 min）任何
对该 agent 的调用直接走 fallback；冷却期结束自动 HALF-OPEN，下一次成功就
关闭熔断重新接收流量。

接口设计
========
- record_success(agent_id) / record_failure(agent_id) — 调用方在 try/except
  里调，本模块自己维护状态
- is_open(agent_id) -> bool — 主路径在调 LLM 前先问，判定是否短路
- get_status(agent_id) -> dict — 运维 / 测试看当前态

零依赖 + 进程内字典；多进程部署后续可换 Redis 后端。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from app.core.env import get_float_env, get_int_env

logger = logging.getLogger(__name__)


# 配置（环境变量可覆盖；默认值面向单机 + 国内 LLM 限流场景）
# 用 get_int_env / get_float_env：非法值自动 fallback default + warning（防 cast 崩溃）。
_WINDOW_SIZE = get_int_env("AGENT_CB_WINDOW", 10, minimum=1, maximum=1000)
_FAILURE_THRESHOLD = get_float_env("AGENT_CB_FAILURE_RATIO", 0.6, minimum=0.0, maximum=1.0)
_COOLDOWN_SECONDS = get_int_env("AGENT_CB_COOLDOWN_SECONDS", 300, minimum=1, maximum=86400)
# 至少要有 N 次最近调用才考虑熔断，防止冷启动时 1 次失败立刻熔断
_MIN_CALLS_BEFORE_TRIP = get_int_env("AGENT_CB_MIN_CALLS", 3, minimum=1, maximum=100)


@dataclass
class _AgentState:
    history: deque = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))  # bool 序列
    opened_at: float = 0.0  # 0 表示 closed
    half_open: bool = False


_states: dict[str, _AgentState] = {}
_lock = threading.Lock()


def _get_state(agent_id: str) -> _AgentState:
    with _lock:
        state = _states.get(agent_id)
        if state is None:
            state = _AgentState()
            _states[agent_id] = state
        return state


def record_success(agent_id: str) -> None:
    """LLM 调用成功调一次。HALF_OPEN 期间的成功会关闭熔断器。"""
    state = _get_state(agent_id)
    with _lock:
        state.history.append(True)
        if state.opened_at and state.half_open:
            logger.info("[circuit-breaker] %s recovered after half-open success", agent_id)
            state.opened_at = 0.0
            state.half_open = False


def record_failure(agent_id: str) -> None:
    """LLM 调用失败调一次。失败率达阈值 → 进入 OPEN。HALF_OPEN 期间的失败会
    重置 cool-down。"""
    state = _get_state(agent_id)
    with _lock:
        state.history.append(False)
        if state.opened_at and state.half_open:
            # half-open 探活又失败 → 重置 cool-down
            logger.warning("[circuit-breaker] %s half-open probe failed, re-opening", agent_id)
            state.opened_at = time.monotonic()
            state.half_open = False
            return
        # 计算失败率
        if len(state.history) < _MIN_CALLS_BEFORE_TRIP:
            return
        failures = sum(1 for ok in state.history if not ok)
        ratio = failures / len(state.history)
        if ratio >= _FAILURE_THRESHOLD and not state.opened_at:
            logger.warning(
                "[circuit-breaker] %s OPEN — failure_ratio=%.2f over last %d calls",
                agent_id, ratio, len(state.history),
            )
            state.opened_at = time.monotonic()


def is_open(agent_id: str) -> bool:
    """主路径调 LLM 前先问：True → 跳过 LLM 直接走 fallback。

    OPEN 状态超过 cooldown_seconds 自动转 HALF_OPEN（仍返 False 让一次试探），
    HALF_OPEN 期间下一次 record_success/failure 决定走向（关 / 重 OPEN）。
    """
    state = _get_state(agent_id)
    with _lock:
        if not state.opened_at:
            return False
        elapsed = time.monotonic() - state.opened_at
        if elapsed >= _COOLDOWN_SECONDS:
            # 转 half-open：放行下一次调用作为探活
            if not state.half_open:
                logger.info("[circuit-breaker] %s entering HALF_OPEN after %ds cooldown", agent_id, int(elapsed))
                state.half_open = True
            return False
        return True


def get_status(agent_id: str) -> dict:
    """运维 / 测试用：返回 agent 当前熔断态 + 失败统计。"""
    state = _get_state(agent_id)
    with _lock:
        history = list(state.history)
        opened_at = state.opened_at
        half_open = state.half_open
    failures = sum(1 for ok in history if not ok)
    total = len(history)
    if opened_at:
        if half_open:
            phase = "half_open"
        elif time.monotonic() - opened_at >= _COOLDOWN_SECONDS:
            phase = "half_open"  # 即将进入 half-open（is_open 调用时实际转换）
        else:
            phase = "open"
    else:
        phase = "closed"
    return {
        "agent_id": agent_id,
        "phase": phase,
        "calls_in_window": total,
        "failures_in_window": failures,
        "failure_ratio": round(failures / total, 3) if total else 0.0,
        "cooldown_remaining_s": max(
            0,
            _COOLDOWN_SECONDS - int(time.monotonic() - opened_at)
        ) if opened_at else 0,
    }


def reset(agent_id: str | None = None) -> None:
    """运维或测试用：清空指定 agent / 全部 agent 的熔断状态。"""
    with _lock:
        if agent_id is None:
            _states.clear()
        else:
            _states.pop(agent_id, None)
