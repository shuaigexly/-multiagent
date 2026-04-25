"""v7.5 测试：vision 工具 / reflection memory / 优先级排序 / shared cache key。"""
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.tools import dispatch_tool, reset_registry
from app.bitable_workflow.agent_cache import _cache_key, _shared_key
from app.core.memory import MemoryHit, format_memory_hits


@pytest.fixture(autouse=True)
def _refresh_registry():
    reset_registry()
    import importlib

    from app.agents import builtin_tools

    importlib.reload(builtin_tools)
    yield
    reset_registry()


# ------------------ vision tool ------------------

@pytest.mark.asyncio
async def test_inspect_image_returns_error_when_vision_disabled(monkeypatch):
    monkeypatch.delenv("LLM_VISION_MODEL", raising=False)
    result = await dispatch_tool("inspect_image", {"image": "https://x.invalid/a.png"})
    assert result.startswith("ERROR:")
    assert "vision disabled" in result


@pytest.mark.asyncio
async def test_inspect_image_calls_analyze_when_enabled(monkeypatch):
    monkeypatch.setenv("LLM_VISION_MODEL", "glm-4v")
    with patch(
        "app.core.vision.analyze_image",
        new=AsyncMock(return_value="MAU=10万 DAU=4万"),
    ) as mock_analyze:
        out = await dispatch_tool(
            "inspect_image",
            {"image": "https://x.invalid/a.png", "focus": "提取数字"},
        )
    assert out == "MAU=10万 DAU=4万"
    args, kwargs = mock_analyze.call_args
    assert args[0] == "https://x.invalid/a.png"
    assert "提取数字" in kwargs.get("prompt", "")


# ------------------ reflection memory format ------------------

def test_format_memory_hits_separates_reflection_first():
    hits = [
        MemoryHit(
            task_text="任务A",
            summary="案例摘要A",
            similarity=0.7,
            created_at="2026-04-25T10:00:00",
            kind="case",
        ),
        MemoryHit(
            task_text="任务A",
            summary="反思：上次没用 fetch_url，下次该用",
            similarity=0.6,
            created_at="2026-04-25T11:00:00",
            kind="reflection",
        ),
    ]
    block = format_memory_hits(hits)
    # reflection 段在前
    refl_idx = block.find("反思")
    case_idx = block.find("案例摘要A")
    assert refl_idx > 0 and case_idx > 0 and refl_idx < case_idx
    assert "经验教训" in block
    assert "不要照搬" in block


def test_format_memory_hits_only_cases_no_reflection_section():
    hits = [
        MemoryHit("t", "summary", 0.5, "", kind="case"),
    ]
    block = format_memory_hits(hits)
    assert "经验教训" not in block
    assert "案例" in block


# ------------------ cache keys ------------------

def test_shared_key_isolates_dimension():
    a = _shared_key("数据复盘", "data_analyst", "abc")
    b = _shared_key("增长优化", "data_analyst", "abc")
    c = _shared_key("数据复盘", "ceo_assistant", "abc")
    d = _shared_key("数据复盘", "data_analyst", "xyz")
    assert a != b  # 不同维度
    assert a != c  # 不同 agent
    assert a != d  # 不同 input hash
    assert "shared:数据复盘" in a or "shared:" in a


def test_task_key_and_shared_key_disjoint():
    t = _cache_key("task-1", "data_analyst", "h1")
    s = _shared_key("数据复盘", "data_analyst", "h1")
    assert t != s
    assert "shared" in s
    assert "shared" not in t


# ------------------ priority sort behavior ------------------

def test_priority_order_sort():
    """模拟 scheduler 中的优先级排序逻辑。"""
    _PRIO_ORDER = {"P0 紧急": 0, "P1 高": 1, "P2 中": 2, "P3 低": 3}
    pending = [
        {"fields": {"优先级": "P3 低", "任务标题": "C"}},
        {"fields": {"优先级": "P0 紧急", "任务标题": "A"}},
        {"fields": {"优先级": "P2 中", "任务标题": "B"}},
        {"fields": {"任务标题": "D"}},  # no priority
        {"fields": {"优先级": "P1 高", "任务标题": "E"}},
    ]
    pending.sort(
        key=lambda r: _PRIO_ORDER.get((r.get("fields") or {}).get("优先级", ""), 99)
    )
    titles = [r["fields"]["任务标题"] for r in pending]
    assert titles == ["A", "E", "B", "C", "D"]
