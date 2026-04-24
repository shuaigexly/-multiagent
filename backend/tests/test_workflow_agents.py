"""测试工作流 Agent 核心逻辑（workflow_agents.py）"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agents.base_agent import AgentResult, ResultSection
from app.bitable_workflow.workflow_agents import (
    _is_failed_result,
    _build_task_description,
    _format_sections,
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
    async def test_linked_field_populated_when_record_id_given(self, ok_result):
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record") as mock_create:
            mock_create.return_value = "rec_new"
            from app.bitable_workflow.workflow_agents import write_agent_outputs
            count = await write_agent_outputs(
                "app_token", "tbl_out", "测试任务", [ok_result], task_record_id="rec_task123"
            )
        assert count == 1
        # create_record(app_token, table_id, fields) → positional index 2 is fields
        call_fields = mock_create.call_args[0][2]
        assert "关联任务" in call_fields
        assert call_fields["关联任务"] == [{"record_id": "rec_task123"}]

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


class TestWriteCeoReport:
    @pytest.mark.asyncio
    async def test_linked_field_populated(self, ceo_result):
        with patch("app.bitable_workflow.workflow_agents.bitable_ops.create_record") as mock_create:
            mock_create.return_value = "rec_report"
            from app.bitable_workflow.workflow_agents import write_ceo_report
            rid = await write_ceo_report(
                "app_token", "tbl_report", "测试任务", ceo_result,
                participant_count=7, task_record_id="rec_task_abc"
            )
        assert rid == "rec_report"
        call_fields = mock_create.call_args[0][2]
        assert "关联任务" in call_fields
        assert call_fields["关联任务"] == [{"record_id": "rec_task_abc"}]

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
