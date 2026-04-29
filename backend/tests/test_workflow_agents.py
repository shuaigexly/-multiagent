"""测试工作流 Agent 核心逻辑（workflow_agents.py）"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agents.base_agent import AgentResult, ResultSection
from app.bitable_workflow.workflow_agents import (
    _is_failed_result,
    _build_task_description,
    _derive_evidence_grade,
    _format_sections,
    _estimate_urgency,
)


class TestIsFailedResult:
    def test_failed_result_detected(self, failed_result):
        assert _is_failed_result(failed_result) is True

    def test_success_result_not_failed(self, ok_result):
        assert _is_failed_result(ok_result) is False

    def test_empty_raw_output(self):
        result = AgentResult(
            agent_id="x", agent_name="X",
            sections=[], action_items=[], raw_output=""
        )
        assert _is_failed_result(result) is False

    def test_failed_prefix_case(self):
        # raw_output 是 str 类型（非 Optional），空字符串是正常情况
        result = AgentResult(
            agent_id="x", agent_name="X",
            sections=[], action_items=[], raw_output="FAILED: timeout"
        )
        assert _is_failed_result(result) is True


class TestBuildTaskDescription:
    def test_full_fields(self):
        fields = {
            "任务标题": "AI产品分析",
            "分析维度": "内容战略",
            "背景说明": "当前竞争激烈",
        }
        desc = _build_task_description(fields)
        assert "AI产品分析" in desc
        assert "内容战略" in desc
        assert "当前竞争激烈" in desc

    def test_missing_background(self):
        fields = {"任务标题": "测试", "分析维度": "综合分析"}
        desc = _build_task_description(fields)
        assert "测试" in desc
        assert "背景说明" not in desc

    def test_empty_fields(self):
        desc = _build_task_description({})
        assert "未命名任务" in desc
        assert "综合分析" in desc


class TestRunTaskPipelineProgress:
    @pytest.mark.asyncio
    async def test_emits_agent_level_events(self, monkeypatch):
        from app.bitable_workflow import workflow_agents

        class FakeAgent:
            def __init__(self, agent_id: str, agent_name: str):
                self.agent_id = agent_id
                self.agent_name = agent_name

        fake_agents = [
            FakeAgent("data_analyst", "数据分析师"),
            FakeAgent("content_manager", "内容负责人"),
            FakeAgent("seo_advisor", "SEO增长顾问"),
            FakeAgent("product_manager", "产品经理"),
            FakeAgent("operations_manager", "运营负责人"),
        ]
        fake_finance = FakeAgent("finance_advisor", "财务顾问")
        fake_ceo = FakeAgent("ceo_assistant", "CEO 助理")

        async def fake_safe_analyze(agent, *_args, **_kwargs):
            return AgentResult(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                sections=[ResultSection(title="结论", content=f"{agent.agent_name} 完成")],
                action_items=["下一步"],
                raw_output=f"{agent.agent_name} 完成",
                confidence_hint=4,
                structured_evidence=[{"claim": "evidence"}],
            )

        events = []

        async def agent_event_callback(event):
            events.append(event)

        monkeypatch.setattr(workflow_agents, "_WAVE1_AGENTS", fake_agents)
        monkeypatch.setattr(workflow_agents, "_WAVE2_AGENTS", [fake_finance])
        monkeypatch.setattr(workflow_agents, "_WAVE3_AGENT", fake_ceo)
        monkeypatch.setattr(workflow_agents, "finance_advisor_agent", fake_finance)
        monkeypatch.setattr(workflow_agents, "ceo_assistant_agent", fake_ceo)
        monkeypatch.setattr(workflow_agents, "_safe_analyze", fake_safe_analyze)

        all_results, ceo_result = await workflow_agents.run_task_pipeline(
            {"任务标题": "可视化事件任务", "分析维度": "综合分析"},
            agent_event_callback=agent_event_callback,
            task_id="rec_task",
        )

        assert len(all_results) == 6
        assert ceo_result.agent_id == "ceo_assistant"
        assert [event["event_type"] for event in events].count("agent.started") == 7
        assert [event["event_type"] for event in events].count("agent.completed") == 7
        assert {event["wave"] for event in events} == {"Wave 1", "Wave 2", "Wave 3"}
        completed = [event for event in events if event["event_type"] == "agent.completed"]
        assert all(event["confidence"] == 4 for event in completed)
        assert all(event["evidence_count"] == 1 for event in completed)
        assert any(event["dependency"] == "汇总全部上游结论" for event in completed)


class TestFormatSections:
    def test_normal_output(self, ok_result):
        out = _format_sections(ok_result, max_chars=2000)
        assert "核心结论" in out
        assert "增长趋势良好" in out

    def test_truncation_applied(self):
        result = AgentResult(
            agent_id="x", agent_name="X",
            sections=[ResultSection(title="长内容", content="A" * 5000)],
            action_items=[], raw_output=""
        )
        out = _format_sections(result, max_chars=200)
        assert len(out) <= 300  # 允许一点额外的标题和省略号开销
        assert "已截断" in out

    def test_no_sections_falls_back_to_raw(self):
        result = AgentResult(
            agent_id="x", agent_name="X",
            sections=[], action_items=[],
            raw_output="raw_content_" * 10
        )
        out = _format_sections(result, max_chars=50)
        assert len(out) <= 50

    def test_multiple_sections_joined(self, ceo_result):
        out = _format_sections(ceo_result, max_chars=5000)
        assert "核心结论" in out
        assert "重要机会" in out
        assert "重要风险" in out


class TestWriteAgentOutputs:
    @pytest.mark.asyncio
    async def test_no_linked_field_written_due_to_platform_limit(self, ok_result):
        """v8.6.1 实测确认：飞书 records 写接口都不支持 LinkedRecord（POST/PUT/batch
        均返回 1254067）。从源头不写关联字段，避免 4xx 噪声。
        逻辑关联通过任务标题 / 任务编号 文本字段维护。"""
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record") as mock_create, \
             patch("app.bitable_workflow.workflow_agents.bitable_ops.update_record") as mock_update:
            mock_create.return_value = "rec_new"
            from app.bitable_workflow.workflow_agents import write_agent_outputs
            count = await write_agent_outputs(
                "app_token", "tbl_out", "测试任务", [ok_result], task_record_id="rec_task123"
            )
        assert count == 1
        # 即使提供了 task_record_id，create 也不应包含 关联任务 字段
        create_fields = mock_create.call_args[0][2]
        assert "关联任务" not in create_fields
        # 不再调 update_record 补关联字段（PUT 接口同样不支持）
        assert not mock_update.called

    @pytest.mark.asyncio
    async def test_no_linked_field_when_no_record_id(self, ok_result):
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record") as mock_create:
            mock_create.return_value = "rec_new"
            from app.bitable_workflow.workflow_agents import write_agent_outputs
            count = await write_agent_outputs(
                "app_token", "tbl_out", "测试任务", [ok_result]
            )
        assert count == 1
        call_fields = mock_create.call_args[0][2]
        assert "关联任务" not in call_fields

    @pytest.mark.asyncio
    async def test_partial_write_returns_count(self, ok_result, failed_result):
        call_count = 0

        async def mock_create(app_token, table_id, fields):
            nonlocal call_count
            call_count += 1
            if "财务顾问" in fields.get("岗位角色", ""):
                raise RuntimeError("写入失败")
            return "rec_ok"

        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record", side_effect=mock_create):
            from app.bitable_workflow.workflow_agents import write_agent_outputs
            count = await write_agent_outputs(
                "app_token", "tbl_out", "任务", [ok_result, failed_result]
            )
        assert count == 1  # 财务顾问写入失败，只成功1条


class TestEstimateUrgency:
    """v8.6.20-r3：紧急度按健康度设上限，避免 🟢 健康 + 紧急度=5 的逻辑悖论。"""

    def test_green_health_caps_at_3(self):
        """🟢 健康 → 即便正文出现 🔴/P0，紧急度最高 3。"""
        result = AgentResult(
            agent_id="ceo", agent_name="CEO 助理",
            sections=[
                ResultSection(title="总体评级", content="🟢 健康"),
                ResultSection(title="重要风险", content="🔴 竞争对手加速布局"),
            ],
            action_items=[],
            raw_output="总体评级：🟢 健康\n## 重要风险\n🔴 紧急 P0 威胁",
            health_hint="🟢",
            structured_actions=[{"summary": "x", "priority": "P0"}],
        )
        assert _estimate_urgency(result) == 3

    def test_yellow_health_caps_at_4(self):
        """🟡 关注 → P0 也最多 4。"""
        result = AgentResult(
            agent_id="ceo", agent_name="CEO 助理",
            sections=[ResultSection(title="总体评级", content="🟡 关注")],
            action_items=[],
            raw_output="总体评级：🟡 关注",
            health_hint="🟡",
            structured_actions=[{"summary": "x", "priority": "P0"}],
        )
        assert _estimate_urgency(result) == 4

    def test_red_health_no_cap(self):
        """🔴 预警 → 不设上限，P0 取 5。"""
        result = AgentResult(
            agent_id="ceo", agent_name="CEO 助理",
            sections=[ResultSection(title="总体评级", content="🔴 预警")],
            action_items=[],
            raw_output="总体评级：🔴 预警",
            health_hint="🔴",
            structured_actions=[{"summary": "x", "priority": "P0"}],
        )
        assert _estimate_urgency(result) == 5

    def test_green_health_p2_unchanged(self):
        """🟢 健康 + P2 → 3（cap 等于原值，不下调）。"""
        result = AgentResult(
            agent_id="ceo", agent_name="CEO 助理",
            sections=[ResultSection(title="总体评级", content="🟢 健康")],
            action_items=[],
            raw_output="总体评级：🟢 健康",
            health_hint="🟢",
            structured_actions=[{"summary": "x", "priority": "P2"}],
        )
        assert _estimate_urgency(result) == 3

    def test_emoji_heuristic_with_green_cap(self):
        """无 structured_actions：emoji 启发式 + 健康度 cap 联动。"""
        result = AgentResult(
            agent_id="ceo", agent_name="CEO 助理",
            sections=[ResultSection(title="总体评级", content="🟢 健康")],
            action_items=[],
            raw_output="总体评级：🟢 健康\n虽然有 🔴 风险点但整体可控",
            health_hint="🟢",
        )
        # raw_output 含 🔴 → emoji 启发式给 5；但 🟢 健康 cap → 3
        assert _estimate_urgency(result) == 3

    def test_white_data_insufficient_forces_urgency_1(self):
        """v8.6.20-r7（审计 #5）：⚪ 数据不足 → 紧急度强制 1，不取 raw_score 默认 3。"""
        result = AgentResult(
            agent_id="ceo", agent_name="CEO 助理",
            sections=[],
            action_items=[],
            raw_output="FALLBACK: LLM unavailable",
            health_hint="⚪",
        )
        assert _estimate_urgency(result) == 1


class TestNormalizeSingleSelect:
    """v8.6.20-r7（审计 #9）：normalize 兼容 NFC/variation selector/全角空格。"""

    def test_handles_variation_selector(self):
        from app.bitable_workflow.workflow_agents import _normalize_singleselect
        allowed = {"🟢 健康", "🟡 关注", "🔴 预警", "⚪ 数据不足"}
        # 带 emoji presentation selector U+FE0F
        out = _normalize_singleselect("🟢️ 健康", allowed, "⚪ 数据不足")
        assert out == "🟢 健康"

    def test_handles_fullwidth_space(self):
        from app.bitable_workflow.workflow_agents import _normalize_singleselect
        allowed = {"🟢 健康"}
        out = _normalize_singleselect("🟢　健康", allowed, "⚪ 数据不足")
        assert out == "🟢 健康"

    def test_handles_zero_width_chars(self):
        from app.bitable_workflow.workflow_agents import _normalize_singleselect
        allowed = {"🟢 健康"}
        out = _normalize_singleselect("🟢​ 健康", allowed, "⚪ 数据不足")
        assert out == "🟢 健康"

    def test_falls_back_when_unknown(self):
        from app.bitable_workflow.workflow_agents import _normalize_singleselect
        out = _normalize_singleselect("瞎写", {"🟢 健康"}, "⚪ 数据不足")
        assert out == "⚪ 数据不足"


class TestWriteCeoReport:
    @pytest.mark.asyncio
    async def test_no_linked_field_due_to_platform_limit(self, ceo_result):
        """v8.6.1: CEO 报告同样不写 LinkedRecord 字段（飞书 API 平台限制）。"""
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record") as mock_create, \
             patch("app.bitable_workflow.workflow_agents.bitable_ops.update_record") as mock_update:
            mock_create.return_value = "rec_report"
            from app.bitable_workflow.workflow_agents import write_ceo_report
            rid = await write_ceo_report(
                "app_token", "tbl_report", "测试任务", ceo_result,
                participant_count=7, task_record_id="rec_task_abc"
            )
        assert rid == "rec_report"
        create_fields = mock_create.call_args[0][2]
        assert "关联任务" not in create_fields
        assert not mock_update.called

    @pytest.mark.asyncio
    async def test_sections_extracted_correctly(self, ceo_result):
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record") as mock_create:
            mock_create.return_value = "rec_r"
            from app.bitable_workflow.workflow_agents import write_ceo_report
            await write_ceo_report(
                "app_token", "tbl_r", "任务", ceo_result, participant_count=7
            )
        fields = mock_create.call_args[0][2]
        assert "整体经营状况稳健" in fields["核心结论"]
        assert "短视频赛道" in fields["重要机会"]
        assert "竞争对手" in fields["重要风险"]
        assert fields["参与岗位数"] == 7.0
        assert fields["一句话结论"]
        assert fields["高管一页纸"]


class TestEvidenceGrading:
    def test_real_data_high_is_hard_evidence(self):
        assert _derive_evidence_grade({
            "source_type": "real_data",
            "confidence": "high",
            "cite": "BI dashboard",
        }) == "硬证据"

    def test_judgment_without_cite_needs_validation(self):
        assert _derive_evidence_grade({
            "source_type": "judgment",
            "confidence": "medium",
            "cite": "",
        }) == "待验证"

    def test_upstream_high_with_cite_is_hard_evidence(self):
        assert _derive_evidence_grade({
            "source_type": "upstream",
            "confidence": "high",
            "cite": "上游岗位分析",
        }) == "硬证据"


class TestWriteEvidenceRecords:
    @pytest.mark.asyncio
    async def test_evidence_grade_written(self, ok_result):
        ok_result.structured_evidence = [{
            "claim": "自然流量回落",
            "source_type": "real_data",
            "evidence": "最近 4 周自然流量下降 12%",
            "confidence": "high",
            "usage": "risk",
            "cite": "GA 周报",
        }]
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_evidence")) as mock_create:
            from app.bitable_workflow.workflow_agents import write_evidence_records
            count = await write_evidence_records("app_token", "tbl_e", "任务", [ok_result])

        assert count == 1
        fields = mock_create.await_args.args[2]
        assert fields["证据等级"] == "硬证据"
        assert fields["进入CEO汇总"] is True
