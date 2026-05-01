"""任务取消注册表（v8.6.20-r43）— 在不重启进程的前提下让用户主动停掉 in-flight 任务。

为什么需要这个
==============
真实使用场景：用户写了一条任务、点了启动后突然发现「数据源贴错了」/「写错维度了」/
「想换 prompt 重跑」。但 7 岗 DAG 一旦进 LLM 阶段，单条任务可能跑 1-3 分钟。
没有取消机制时只能干等：浪费 LLM tokens + 写出无意义的报告。

机制
====
- 简单进程内 set[record_id]：CO 操作 ms 级、O(1) 查询
- 调用方在每个 await 点（或至少每个 agent 调用前）调 raise_if_cancelled
- 取消信号在进程重启后自然消失 — 重启后的 cycle 会从 Bitable 重新拉状态判断

接口
====
- mark_cancelled(record_id) — 标记一条任务为待取消
- is_cancelled(record_id) -> bool
- raise_if_cancelled(record_id) — 触发 TaskCancelled 异常给 caller 处理
- clear_cancelled(record_id) — 任务真的进入终态后清掉，避免长期占用内存
- list_cancelled() -> list[str]（运维 / telemetry 用）

后续可平滑切到 Redis 后端（多进程协同），接口稳定。
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class TaskCancelled(RuntimeError):
    """主动取消信号 — 不应被业务路径的 generic except 吞掉。

    继承 RuntimeError 而非 BaseException：保证 try/except RuntimeError 抓得到，
    但 try/except Exception 也能正常捕获、记录、清理后再 re-raise。
    """


_cancelled_ids: set[str] = set()
_lock = threading.Lock()


def _normalize(record_id: object) -> str:
    if not isinstance(record_id, str):
        return ""
    return record_id.strip()


def mark_cancelled(record_id: str) -> bool:
    """把 record_id 标记为待取消。返回 True 表示新加，False 表示已经在表里。"""
    rid = _normalize(record_id)
    if not rid:
        return False
    with _lock:
        if rid in _cancelled_ids:
            return False
        _cancelled_ids.add(rid)
        logger.info("[cancel] task=%s queued for cancellation", rid)
        return True


def is_cancelled(record_id: str) -> bool:
    rid = _normalize(record_id)
    if not rid:
        return False
    with _lock:
        return rid in _cancelled_ids


def raise_if_cancelled(record_id: str) -> None:
    """主路径检查点：命中 → 抛 TaskCancelled，让上层走清理 + 标记 Bitable 状态。"""
    if is_cancelled(record_id):
        raise TaskCancelled(f"task {record_id} cancelled by user")


def clear_cancelled(record_id: str) -> bool:
    """任务进入终态后调，避免长期占用内存。返回 True 表示清掉了，False 表示原本就不在。"""
    rid = _normalize(record_id)
    if not rid:
        return False
    with _lock:
        if rid in _cancelled_ids:
            _cancelled_ids.discard(rid)
            return True
        return False


def list_cancelled() -> list[str]:
    """运维 / telemetry 看当前还有多少 in-flight 取消请求。"""
    with _lock:
        return sorted(_cancelled_ids)


def reset_for_tests() -> None:
    """单元测试用：清空所有状态。"""
    with _lock:
        _cancelled_ids.clear()
