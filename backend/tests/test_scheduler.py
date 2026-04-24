"""测试调度器核心逻辑（scheduler.py）"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

from app.agents.base_agent import AgentResult, ResultSection
from app.bitable_workflow.schema import Status


TABLE_IDS = {
    "task": "tbl_task",
    "output": "tbl_output",
    "report": "tbl_report",
    "performance": "tbl_perf",
}


class TestFollowupTasks:
    @pytest.mark.asyncio
    async def test_followup_tasks_created_from_action_items(self, ceo_result):
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record") as mock_create:
            mock_create.return_value = "rec_followup"
            from app.bitable_workflow.scheduler import _create_followup_tasks
            await _create_followup_tasks("app_token", "tbl_task", "原始任务", ceo_result)

        # ceo_result 有 3 条 action_items，应全部生成跟进任务
        assert mock_create.call_count == 3
        first_call_fields = mock_create.call_args_list[0][0][2]
        assert first_call_fields["状态"] == Status.PENDING
        assert first_call_fields["任务标题"].startswith("[跟进]")
        assert "原始任务" in first_call_fields["背景说明"]

    @pytest.mark.asyncio
    async def test_no_followup_for_followup_tasks(self, ceo_result):
        """[跟进] 任务不应再生成二级跟进，避免无限循环"""
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record") as mock_create:
            from app.bitable_workflow.scheduler import _create_followup_tasks
            await _create_followup_tasks("app_token", "tbl_task", "[跟进] 某个行动项", ceo_result)
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_followup_when_no_action_items(self):
        result = AgentResult(
            agent_id="ceo_assistant", agent_name="CEO 助理",
            sections=[], action_items=[], raw_output="完成"
        )
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record") as mock_create:
            from app.bitable_workflow.scheduler import _create_followup_tasks
            await _create_followup_tasks("app_token", "tbl_task", "任务", result)
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_3_followup_tasks(self):
        result = AgentResult(
            agent_id="ceo_assistant", agent_name="CEO 助理",
            sections=[], action_items=["行动1", "行动2", "行动3", "行动4", "行动5"],
            raw_output="完成"
        )
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record") as mock_create:
            mock_create.return_value = "rec_x"
            from app.bitable_workflow.scheduler import _create_followup_tasks
            await _create_followup_tasks("app_token", "tbl_task", "任务", result)
        assert mock_create.call_count == 3, "最多只生成 3 条跟进任务"


class TestSendCompletionMessage:
    @pytest.mark.asyncio
    async def test_message_sent_when_chat_configured(self, ceo_result):
        """配置了 chat_id 时应成功发送消息"""
        import app.feishu.im as im_module  # 确保模块已加载，patch 才能找到
        mock_send = AsyncMock(return_value={"message_id": "msg_123"})
        with patch.object(im_module, "send_card_message", mock_send):
            from app.bitable_workflow.scheduler import _send_completion_message
            await _send_completion_message("测试任务", ceo_result)
        mock_send.assert_called_once()
        assert "测试任务" in str(mock_send.call_args)

    @pytest.mark.asyncio
    async def test_message_failure_does_not_raise(self, ceo_result):
        """飞书消息发送失败不应抛出异常，主流程不受影响"""
        import app.feishu.im as im_module
        with patch.object(im_module, "send_card_message", side_effect=Exception("网络错误")):
            from app.bitable_workflow.scheduler import _send_completion_message
            await _send_completion_message("测试任务", ceo_result)  # 不应抛出

    @pytest.mark.asyncio
    async def test_no_chat_id_silently_skipped(self, ceo_result):
        """未配置 chat_id 时静默跳过，不应抛出"""
        import app.feishu.im as im_module
        with patch.object(im_module, "send_card_message", side_effect=ValueError("未配置飞书群 ID")):
            from app.bitable_workflow.scheduler import _send_completion_message
            await _send_completion_message("测试任务", ceo_result)  # 不应抛出


class TestRunOneCycle:
    @pytest.mark.asyncio
    async def test_no_pending_tasks_returns_zero(self):
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", return_value=[]):
            from app.bitable_workflow.scheduler import run_one_cycle
            result = await run_one_cycle("app_token", TABLE_IDS)
        assert result == 0

    @pytest.mark.asyncio
    async def test_stuck_analyzing_records_reset(self):
        stuck_record = {
            "record_id": "rec_stuck",
            "fields": {
                "任务标题": "卡住的任务",
                "状态": Status.ANALYZING,
                "最近更新": "2000-01-01 00:00",
            },
        }

        async def mock_list_records(app_token, table_id, filter_expr=None, **kwargs):
            if Status.ANALYZING in (filter_expr or ""):
                return [stuck_record]
            return []  # no pending tasks

        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", side_effect=mock_list_records):
            with patch("app.bitable_workflow.scheduler.bitable_ops.update_record") as mock_update:
                mock_update.return_value = None
                from app.bitable_workflow.scheduler import run_one_cycle
                result = await run_one_cycle("app_token", TABLE_IDS)

        mock_update.assert_called_once_with(
            "app_token", "tbl_task", "rec_stuck", {"状态": Status.PENDING}
        )
        assert result == 0
