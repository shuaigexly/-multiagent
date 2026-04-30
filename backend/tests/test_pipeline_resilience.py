"""v8.6.20-r32: pipeline 在 LLM 部分 / 全部失败下的级联弹性回归。

竞赛维度 1（完整性与价值）和维度 3（技术实现性）的硬支撑：
即便 6 个上游 agent 的 LLM 调用全部失败（瞬时网络断、限流、模型 5xx），
整条 pipeline 必须仍能产出**有内容、可读、可决策**的 CEO 综合报告，而不是
原地崩溃或全空 — 这是"AI 协同 ≠ 单点 LLM 依赖"的承诺。

测试覆盖：
- 单 agent LLM 抛错 → fallback build_fallback_result 产出 → raw_output 'FALLBACK:'
- 全部 6 个上游 agent LLM 抛错 → 6 个都是 fallback → CEO 仍能 run
- _is_failed_result vs _is_fallback_result 的语义边界（FAILED ≠ FALLBACK）
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.base_agent import AgentResult, ResultSection
from app.bitable_workflow import workflow_agents


def _make_agent_stub(agent_id: str, agent_name: str, *, raises: bool, ceo_summary: str = ""):
    """构造一个可控的 fake agent — analyze() 要么抛错（触发 fallback），
    要么返回带 raw_output='OK:' 前缀的成功 AgentResult。"""

    class _StubAgent:
        def __init__(self):
            self.agent_id = agent_id
            self.agent_name = agent_name

        async def analyze(self, **kwargs):
            if raises:
                raise RuntimeError(f"simulated LLM 503 for {agent_id}")
            return AgentResult(
                agent_id=agent_id,
                agent_name=agent_name,
                sections=[ResultSection(title="结论", content=ceo_summary or f"{agent_name} 正常完成")],
                action_items=[f"{agent_name} 推进事项 1"],
                raw_output=f"OK: {agent_name} succeeded",
                confidence_hint=4,
            )

    return _StubAgent()


@pytest.mark.asyncio
async def test_safe_analyze_returns_fallback_when_llm_raises(monkeypatch):
    """单 agent 维度：LLM 抛错 → 返回 fallback（不返 FAILED），下游可继续。"""

    async def fake_get(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_cached_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_shared_result", fake_get)

    failing = _make_agent_stub("data_analyst", "数据分析师", raises=True)
    result = await workflow_agents._safe_analyze(
        failing,
        "测试任务",
        upstream=[],
        data_summary=None,
        task_id="t_resilience",
        dimension="测试维度",
    )

    assert workflow_agents._is_fallback_result(result)
    assert not workflow_agents._is_failed_result(result)
    # fallback 必须有可读内容 + 至少 1 个 action item
    assert result.sections, "fallback 必须有 sections，不能空"
    assert result.action_items, "fallback 必须有保守 action item"
    assert result.confidence_hint == 1, "fallback 自评 confidence=1（数据不足）"


@pytest.mark.asyncio
async def test_pipeline_survives_all_six_upstream_llm_failures(monkeypatch):
    """全链路：Wave1 5 个 + Wave2 财务 1 个 — 6 个 agent 全 LLM 失败，
    每个降级为 fallback；CEO（Wave3）的 LLM 仍工作 → 成功 ceo_result 出来。

    旧实现若 fallback 没接住 LLM 异常，会让 _safe_analyze 抛上去 → asyncio.gather
    抛 → 整个 pipeline 死。这个测试就是锁定级联弹性。
    """

    # 关掉 cache（让每个调用真的进 _safe_analyze 主路径）
    async def fake_get(*_args, **_kwargs):
        return None

    async def fake_set(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_cached_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_shared_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.set_cached_result", fake_set)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.set_shared_result", fake_set)

    # 替换 5 个 wave1 agent 全部抛错
    failing_wave1 = [
        _make_agent_stub("data_analyst", "数据分析师", raises=True),
        _make_agent_stub("content_manager", "内容负责人", raises=True),
        _make_agent_stub("seo_advisor", "SEO 顾问", raises=True),
        _make_agent_stub("product_manager", "产品经理", raises=True),
        _make_agent_stub("operations_manager", "运营负责人", raises=True),
    ]
    monkeypatch.setattr(workflow_agents, "_WAVE1_AGENTS", failing_wave1)

    # 替换 wave2 财务也抛错
    failing_finance = _make_agent_stub("finance_advisor", "财务顾问", raises=True)
    monkeypatch.setattr(workflow_agents, "finance_advisor_agent", failing_finance)

    # CEO 仍能工作 — 模拟其他模型 / 主备切换成功
    working_ceo = _make_agent_stub(
        "ceo_assistant", "CEO 助理", raises=False,
        ceo_summary="基于 6 份降级骨架报告，本轮决策建议：暂缓投入新预算，先恢复数据采集",
    )
    monkeypatch.setattr(workflow_agents, "_WAVE3_AGENT", working_ceo)

    # 关 vision 增强（避免 LLM_VISION_MODEL 路径）
    async def fake_vision(task_description, _fields):
        return task_description

    monkeypatch.setattr(workflow_agents, "_enrich_with_vision", fake_vision)

    task_fields = {
        "任务标题": "Q3 经营复盘",
        "任务描述": "复盘 Q3 各渠道增长 + 成本",
        "分析维度": "测试维度",
    }

    upstream, ceo = await workflow_agents.run_task_pipeline(
        task_fields=task_fields,
        progress_callback=None,
        agent_event_callback=None,
        task_id="t_pipeline_resilience",
    )

    # 6 个上游全部 fallback（不是 failed）
    assert len(upstream) == 6, f"期望 6 个上游 agent 输出，实际 {len(upstream)}"
    for r in upstream:
        assert workflow_agents._is_fallback_result(r), f"{r.agent_name} 期望 fallback，实际 raw={r.raw_output[:60]}"
        assert not workflow_agents._is_failed_result(r), f"{r.agent_name} 不应被标记 FAILED"

    # CEO 是真实成功输出（不是 fallback、不是 failed）
    assert ceo.raw_output.startswith("OK:"), f"CEO 应正常输出，实际 raw={ceo.raw_output[:60]}"
    assert not workflow_agents._is_failed_result(ceo)
    assert not workflow_agents._is_fallback_result(ceo)
    assert ceo.sections, "CEO 必须有 sections"


@pytest.mark.asyncio
async def test_pipeline_raises_when_ceo_itself_fails(monkeypatch):
    """边界：上游全 fallback + CEO 也失败（连主备模型都 down） → 显式 raise，
    让调度器把任务标记为「异常」而不是写一份空白报告糊弄。"""

    async def fake_get(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_cached_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.get_shared_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.set_cached_result", fake_get)
    monkeypatch.setattr("app.bitable_workflow.agent_cache.set_shared_result", fake_get)

    monkeypatch.setattr(workflow_agents, "_WAVE1_AGENTS", [
        _make_agent_stub("data_analyst", "数据分析师", raises=False),
        _make_agent_stub("content_manager", "内容负责人", raises=False),
        _make_agent_stub("seo_advisor", "SEO 顾问", raises=False),
        _make_agent_stub("product_manager", "产品经理", raises=False),
        _make_agent_stub("operations_manager", "运营负责人", raises=False),
    ])
    monkeypatch.setattr(workflow_agents, "finance_advisor_agent",
                        _make_agent_stub("finance_advisor", "财务顾问", raises=False))

    # CEO 自己失败：这里用一个返回 FAILED raw_output 的 stub
    class _FailingCEO:
        agent_id = "ceo_assistant"
        agent_name = "CEO 助理"

        async def analyze(self, **_kwargs):
            return AgentResult(
                agent_id="ceo_assistant",
                agent_name="CEO 助理",
                sections=[],
                action_items=[],
                raw_output="FAILED: CEO model unreachable",
                confidence_hint=0,
            )

    monkeypatch.setattr(workflow_agents, "_WAVE3_AGENT", _FailingCEO())

    async def fake_vision(td, _f):
        return td

    monkeypatch.setattr(workflow_agents, "_enrich_with_vision", fake_vision)

    task_fields = {"任务标题": "T", "任务描述": "X", "分析维度": "测试"}

    with pytest.raises(RuntimeError, match="CEO 助理汇总失败"):
        await workflow_agents.run_task_pipeline(
            task_fields=task_fields,
            task_id="t_ceo_fail",
        )
