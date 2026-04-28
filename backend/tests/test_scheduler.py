"""测试调度器核心逻辑（scheduler.py）"""
import asyncio
from contextlib import ExitStack

import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

from app.agents.base_agent import AgentResult, ResultSection
from app.bitable_workflow.schema import Status


TABLE_IDS = {
    "task": "tbl_task",
    "output": "tbl_output",
    "report": "tbl_report",
    "performance": "tbl_perf",
    "action": "tbl_action",
    "review_history": "tbl_review_history",
    "archive": "tbl_archive",
    "automation_log": "tbl_automation_log",
    "template": "tbl_template",
}


class TestFollowupTasks:
    @pytest.mark.asyncio
    async def test_followup_tasks_created_from_action_items(self, ceo_result):
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields") as mock_create:
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
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields") as mock_create:
            from app.bitable_workflow.scheduler import _create_followup_tasks
            await _create_followup_tasks("app_token", "tbl_task", "[跟进] 某个行动项", ceo_result)
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_followup_when_no_action_items(self):
        result = AgentResult(
            agent_id="ceo_assistant", agent_name="CEO 助理",
            sections=[], action_items=[], raw_output="完成"
        )
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields") as mock_create:
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
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields") as mock_create:
            mock_create.return_value = "rec_x"
            from app.bitable_workflow.scheduler import _create_followup_tasks
            await _create_followup_tasks("app_token", "tbl_task", "任务", result)
        assert mock_create.call_count == 3, "最多只生成 3 条跟进任务"

    @pytest.mark.asyncio
    async def test_followup_tasks_write_execution_action_log(self):
        result = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[],
            action_items=[],
            raw_output="完成",
            decision_items=[
                {"summary": "立即通知销售团队推进重点客户", "type": "execute_now"},
                {"summary": "补齐线索质量分析", "type": "need_data"},
            ],
        )
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_x")):
            with patch("app.feishu.task.batch_create_tasks", new=AsyncMock(return_value=[{"guid": "task_1"}])) as mock_batch:
                with patch("app.bitable_workflow.scheduler._write_action_record", new=AsyncMock()) as mock_action:
                    from app.bitable_workflow.scheduler import _create_followup_tasks

                    await _create_followup_tasks(
                        "app_token",
                        "tbl_task",
                        "经营复盘",
                        result,
                        action_tid="tbl_action",
                        automation_log_tid="tbl_automation_log",
                        route="直接执行",
                    )

        mock_batch.assert_awaited_once()
        assert any(
            call.args[3] == "创建执行任务" and call.args[4] == "已完成"
            for call in mock_action.await_args_list
        )

    @pytest.mark.asyncio
    async def test_followup_tasks_skip_duplicate_open_record(self):
        result = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[],
            action_items=[],
            raw_output="完成",
            decision_items=[
                {"summary": "补齐线索质量分析", "type": "need_data"},
            ],
        )
        existing = [{
            "record_id": "rec_existing",
            "fields": {"状态": Status.PENDING},
        }]
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=existing)):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock()) as mock_create:
                with patch("app.bitable_workflow.scheduler._write_action_record", new=AsyncMock()) as mock_action:
                    with patch("app.bitable_workflow.scheduler._write_automation_log", new=AsyncMock()):
                        from app.bitable_workflow.scheduler import _create_followup_tasks

                        await _create_followup_tasks(
                            "app_token",
                            "tbl_task",
                            "经营复盘",
                            result,
                            action_tid="tbl_action",
                            automation_log_tid="tbl_automation_log",
                            route="补数复核",
                        )

        mock_create.assert_not_awaited()
        assert mock_action.await_args.args[3] == "自动跟进任务"
        assert mock_action.await_args.args[4] == "已跳过"

    @pytest.mark.asyncio
    async def test_followup_tasks_do_not_create_feishu_tasks_before_approval(self):
        result = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[],
            action_items=[],
            raw_output="完成",
            decision_items=[
                {"summary": "批准 Q3 预算追加", "type": "ceo_decision"},
                {"summary": "通知销售团队跟进重点客户", "type": "execute_now"},
            ],
        )
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=[])):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_followup")):
                with patch("app.feishu.task.batch_create_tasks", new=AsyncMock(return_value=[{"guid": "task_1"}])) as mock_batch:
                    from app.bitable_workflow.scheduler import _create_followup_tasks

                    await _create_followup_tasks(
                        "app_token",
                        "tbl_task",
                        "经营复盘",
                        result,
                        route="等待拍板",
                    )

        mock_batch.assert_not_awaited()


class TestSendCompletionMessage:
    @pytest.mark.asyncio
    async def test_message_sent_when_chat_configured(self, ceo_result):
        """v8.6.19 — 配置了 chat_id 时应成功发送消息（新签名 5 参数）"""
        import app.feishu.im as im_module
        mock_send = AsyncMock(return_value={"message_id": "msg_123"})
        with patch.object(im_module, "send_card_message", mock_send):
            from app.bitable_workflow.scheduler import _send_completion_message
            await _send_completion_message("app_x", "tbl_x", "rec_x", "测试任务", ceo_result)
        mock_send.assert_called_once()
        assert "测试任务" in str(mock_send.call_args)

    @pytest.mark.asyncio
    async def test_message_sent_writes_action_log(self, ceo_result):
        import app.feishu.im as im_module
        mock_send = AsyncMock(return_value={"message_id": "msg_123"})
        with patch.object(im_module, "send_card_message", mock_send):
            with patch("app.bitable_workflow.scheduler._write_action_record", new=AsyncMock()) as mock_action:
                from app.bitable_workflow.scheduler import _send_completion_message

                await _send_completion_message(
                    "app_x",
                    "tbl_x",
                    "rec_x",
                    "测试任务",
                    ceo_result,
                    action_tid="tbl_action",
                    automation_log_tid="tbl_automation_log",
                    route="直接汇报",
                )

        assert mock_action.await_args.args[3] == "发送汇报"
        assert mock_action.await_args.args[4] == "已完成"

    @pytest.mark.asyncio
    async def test_message_failure_does_not_raise(self, ceo_result):
        """飞书消息发送失败不应抛出异常，主流程不受影响"""
        import app.feishu.im as im_module
        with patch.object(im_module, "send_card_message", side_effect=Exception("网络错误")):
            from app.bitable_workflow.scheduler import _send_completion_message
            await _send_completion_message("app_x", "tbl_x", "rec_x", "测试任务", ceo_result)

    @pytest.mark.asyncio
    async def test_no_chat_id_silently_skipped(self, ceo_result):
        """未配置 chat_id 时静默跳过，不应抛出"""
        import app.feishu.im as im_module
        with patch.object(im_module, "send_card_message", side_effect=ValueError("未配置飞书群 ID")):
            from app.bitable_workflow.scheduler import _send_completion_message
            await _send_completion_message("app_x", "tbl_x", "rec_x", "测试任务", ceo_result)


class TestRunOneCycle:
    @pytest.mark.asyncio
    async def test_no_pending_tasks_returns_zero(self):
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", return_value=[]):
            from app.bitable_workflow.scheduler import run_one_cycle
            result = await run_one_cycle("app_token", TABLE_IDS)
        assert result == 0

    @pytest.mark.asyncio
    async def test_lock_renewal_failure_aborts_running_cycle(self, monkeypatch):
        from app.bitable_workflow import scheduler

        released = False
        cancelled = False

        async def fake_acquire(_app_token, _task_tid):
            return object(), "owner"

        async def fake_release(_client, _owner, _app_token, _task_tid):
            nonlocal released
            released = True

        async def fake_renew(_client, _owner, _app_token, _task_tid):
            await asyncio.sleep(0)
            raise RuntimeError("lost lock")

        async def fake_run(_app_token, _table_ids):
            nonlocal cancelled
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled = True
                raise

        monkeypatch.setattr(scheduler, "_acquire_cycle_lock", fake_acquire)
        monkeypatch.setattr(scheduler, "_release_cycle_lock", fake_release)
        monkeypatch.setattr(scheduler, "_renew_cycle_lock", fake_renew)
        monkeypatch.setattr(scheduler, "_run_one_cycle_locked", fake_run)

        with pytest.raises(RuntimeError, match="renewal failed"):
            await scheduler.run_one_cycle("app_token", TABLE_IDS)

        assert cancelled is True
        assert released is True

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


class TestReviewRecheckTasks:
    @pytest.mark.asyncio
    async def test_review_recheck_task_created(self):
        review_fields = {
            "推荐动作": "补数后复核",
            "需补数事项": "- 补齐关键渠道转化\n- 核验口径",
        }
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=[])):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_recheck")) as mock_create:
                from app.bitable_workflow.scheduler import _create_review_recheck_task

                await _create_review_recheck_task(
                    "app_token",
                    "tbl_task",
                    "增长复盘任务",
                    review_fields,
                    parent_task_number="12",
                )

        mock_create.assert_awaited_once()
        fields = mock_create.await_args.args[2]
        assert fields["任务标题"].startswith("[复核]")
        assert fields["输出目的"] == "补数核验"
        assert fields["依赖任务编号"] == "12"

    @pytest.mark.asyncio
    async def test_review_recheck_task_applies_template_defaults(self):
        review_fields = {
            "推荐动作": "补数后复核",
            "需补数事项": "- 补齐关键渠道转化\n- 核验口径",
        }
        template_rows = [
            {
                "record_id": "rec_tpl",
                "fields": {
                    "启用": True,
                    "模板名称": "补数复核默认模板",
                    "适用输出目的": "补数核验",
                    "默认汇报对象": "经营分析会",
                    "默认执行负责人": "运营负责人",
                    "默认复核负责人": "数据分析负责人",
                    "默认复核SLA小时": 24,
                },
            }
        ]
        with patch(
            "app.bitable_workflow.scheduler.bitable_ops.list_records",
            new=AsyncMock(side_effect=[[], template_rows]),
        ):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_recheck")) as mock_create:
                from app.bitable_workflow.scheduler import _create_review_recheck_task

                await _create_review_recheck_task(
                    "app_token",
                    "tbl_task",
                    "增长复盘任务",
                    review_fields,
                    template_tid="tbl_template",
                )

        fields = mock_create.await_args.args[2]
        assert fields["套用模板"] == "补数复核默认模板"
        assert fields["汇报对象"] == "经营分析会"
        assert fields["执行负责人"] == "运营负责人"
        assert fields["复核负责人"] == "数据分析负责人"
        assert fields["复核SLA小时"] == 24

    @pytest.mark.asyncio
    async def test_review_recheck_task_initializes_native_contract_fields(self):
        review_fields = {
            "推荐动作": "建议重跑",
            "需补数事项": "",
        }
        with patch(
            "app.bitable_workflow.scheduler.bitable_ops.list_records",
            new=AsyncMock(return_value=[]),
        ):
            with patch(
                "app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields",
                new=AsyncMock(return_value="rec_recheck"),
            ) as mock_create:
                from app.bitable_workflow.scheduler import _create_review_recheck_task

                await _create_review_recheck_task(
                    "app_token",
                    "tbl_task",
                    "增长复盘任务",
                    review_fields,
                )

        fields = mock_create.await_args.args[2]
        optional_keys = mock_create.await_args.kwargs.get("optional_keys") or []
        assert fields["当前责任角色"] == "系统调度"
        assert fields["当前责任人"] == "系统"
        assert fields["当前原生动作"] == "等待分析完成"
        assert fields["异常状态"] == "正常"
        assert fields["异常类型"] == "无"
        assert "当前责任角色" in optional_keys
        assert "当前责任人" in optional_keys
        assert "当前原生动作" in optional_keys
        assert "异常状态" in optional_keys
        assert "异常类型" in optional_keys
        assert "异常说明" in optional_keys

    @pytest.mark.asyncio
    async def test_review_recheck_task_skips_duplicate_open_record(self):
        review_fields = {
            "推荐动作": "建议重跑",
            "需补数事项": "",
        }
        existing = [{
            "record_id": "rec_existing",
            "fields": {"状态": Status.PENDING},
        }]
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=existing)):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock()) as mock_create:
                from app.bitable_workflow.scheduler import _create_review_recheck_task

                await _create_review_recheck_task(
                    "app_token",
                    "tbl_task",
                    "增长复盘任务",
                    review_fields,
                )

        mock_create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_review_recheck_skip_duplicate_writes_action_log(self):
        review_fields = {
            "推荐动作": "建议重跑",
            "需补数事项": "",
        }
        existing = [{
            "record_id": "rec_existing",
            "fields": {"状态": Status.PENDING},
        }]
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=existing)):
            with patch("app.bitable_workflow.scheduler._write_action_record", new=AsyncMock()) as mock_action:
                from app.bitable_workflow.scheduler import _create_review_recheck_task

                await _create_review_recheck_task(
                    "app_token",
                    "tbl_task",
                    "增长复盘任务",
                    review_fields,
                    action_tid="tbl_action",
                    automation_log_tid="tbl_automation_log",
                    route="重新分析",
                )

        assert mock_action.await_args.args[3] == "创建复核任务"
        assert mock_action.await_args.args[4] == "已跳过"


class TestReviewHistoryAndArchive:
    @pytest.mark.asyncio
    async def test_write_review_history_record_computes_round_and_diff(self):
        existing = [{
            "record_id": "rec_old",
            "fields": {"推荐动作": "补数后复核", "生成时间": "2026-04-27 10:00"},
        }]
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=existing)):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_new")) as mock_create:
                from app.bitable_workflow.scheduler import _write_review_history_record

                payload = await _write_review_history_record(
                    "app_token",
                    "tbl_review_history",
                    "增长复盘任务",
                    "12",
                    {
                        "推荐动作": "建议重跑",
                        "评审摘要": "关键证据不足，需要重跑。",
                        "评审结论": "建议重跑",
                        "需补数事项": "- 拉新渠道拆解",
                    },
                    route="重新分析",
                    record_id="rec_task",
                )

        assert payload["round"] == 2
        fields = mock_create.await_args.args[2]
        assert fields["复核轮次"] == 2.0
        assert "前次推荐动作：补数后复核" in fields["新旧结论差异"]

    @pytest.mark.asyncio
    async def test_write_review_history_record_prefers_record_id_over_same_title_rows(self):
        async def fake_list_records(_app_token, _table_id, filter_expr=None, max_records=100):
            assert "关联记录ID" in (filter_expr or "")
            return []

        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(side_effect=fake_list_records)):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_new")) as mock_create:
                from app.bitable_workflow.scheduler import _write_review_history_record

                payload = await _write_review_history_record(
                    "app_token",
                    "tbl_review_history",
                    "增长复盘任务",
                    "12",
                    {
                        "推荐动作": "建议重跑",
                        "评审结论": "建议重跑",
                    },
                    route="重新分析",
                    record_id="rec_task_unique",
                )

        assert payload["round"] == 1
        fields = mock_create.await_args.args[2]
        assert fields["复核轮次"] == 1.0
        assert fields["关联记录ID"] == "rec_task_unique"

    @pytest.mark.asyncio
    async def test_write_delivery_archive_record_returns_version_and_status(self, ceo_result):
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=[{"record_id": "rec_old", "fields": {}}])):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_archive")) as mock_create:
                from app.bitable_workflow.scheduler import _write_delivery_archive_record

                payload = await _write_delivery_archive_record(
                    "app_token",
                    "tbl_archive",
                    "增长复盘任务",
                    "12",
                    {"目标对象": "CEO", "执行负责人": "运营负责人A"},
                    {
                        "最新评审动作": "直接采用",
                        "最新管理摘要": "增长放缓，需要先优化投放结构。",
                        "汇报就绪度": 4,
                        "工作流消息包": "任务：增长复盘任务",
                    },
                    ceo_result,
                    "直接执行",
                    record_id="rec_task",
                )

        assert payload["version"] == "v2"
        assert payload["archive_status"] == "待执行"
        fields = mock_create.await_args.args[2]
        assert fields["归档状态"] == "待执行"
        assert fields["汇报版本号"] == "v2"

    @pytest.mark.asyncio
    async def test_write_delivery_archive_record_prefers_record_id_over_same_title_rows(self, ceo_result):
        async def fake_list_records(_app_token, _table_id, filter_expr=None, max_records=100):
            assert "关联记录ID" in (filter_expr or "")
            return []

        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(side_effect=fake_list_records)):
            with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_archive")) as mock_create:
                from app.bitable_workflow.scheduler import _write_delivery_archive_record

                payload = await _write_delivery_archive_record(
                    "app_token",
                    "tbl_archive",
                    "增长复盘任务",
                    "12",
                    {"目标对象": "CEO", "执行负责人": "运营负责人A"},
                    {
                        "最新评审动作": "直接采用",
                        "最新管理摘要": "增长放缓，需要先优化投放结构。",
                        "汇报就绪度": 4,
                        "工作流消息包": "任务：增长复盘任务",
                    },
                    ceo_result,
                    "直接执行",
                    record_id="rec_task_unique",
                )

        assert payload["version"] == "v1"
        fields = mock_create.await_args.args[2]
        assert fields["汇报版本号"] == "v1"
        assert fields["关联记录ID"] == "rec_task_unique"


class TestAutomationLog:
    @pytest.mark.asyncio
    async def test_write_automation_log_writes_expected_fields(self):
        with patch("app.bitable_workflow.scheduler.bitable_ops.create_record_optional_fields", new=AsyncMock(return_value="rec_log")) as mock_create:
            from app.bitable_workflow.scheduler import _write_automation_log

            await _write_automation_log(
                "app_token",
                "tbl_automation_log",
                "增长复盘任务",
                "飞书消息通知",
                "已完成",
                route="直接汇报",
                trigger="任务完成",
                summary="已发送卡片",
                detail="https://feishu.cn/base/xxx",
                record_id="rec_task",
            )

        fields = mock_create.await_args.args[2]
        assert fields["节点名称"] == "飞书消息通知"
        assert fields["执行状态"] == "已完成"
        assert fields["工作流路由"] == "直接汇报"


class TestTemplateCenter:
    @pytest.mark.asyncio
    async def test_apply_template_config_overrides_packages_and_defaults(self, ceo_result):
        rows = [{
            "record_id": "rec_tpl",
            "fields": {
                "启用": True,
                "模板名称": "执行跟进默认模板",
                "适用工作流路由": "直接执行",
                "适用输出目的": "执行跟进",
                "汇报模板": "任务：{task_title}\\n对象：{audience}",
                "执行模板": "负责人：{execution_owner}\\n执行项：{execute_items}",
                "默认汇报对象": "经营会",
                "默认拍板负责人": "经营拍板人",
                "默认执行负责人": "运营负责人A",
                "默认复核负责人": "分析负责人B",
                "默认复盘负责人": "复盘负责人C",
                "默认复核SLA小时": 12,
            },
        }]
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=rows)):
            from app.bitable_workflow.scheduler import _apply_template_config

            payload = await _apply_template_config(
                "app_token",
                "tbl_template",
                "增长复盘任务",
                {"输出目的": "执行跟进"},
                {"推荐动作": "直接采用"},
                AgentResult(
                    agent_id="ceo_assistant",
                    agent_name="CEO 助理",
                    sections=[ResultSection(title="管理摘要", content="需要本周推进低 ROI 渠道调整。")],
                    action_items=[],
                    raw_output="summary",
                    decision_items=[{"summary": "调整低 ROI 渠道", "type": "execute_now"}],
                ),
                {
                    "工作流路由": "直接执行",
                    "工作流消息包": "old-message",
                    "工作流执行包": "old-exec",
                    "汇报对象": "",
                    "执行负责人": "",
                    "复核负责人": "",
                    "复核SLA小时": 0,
                },
            )

        assert "任务：增长复盘任务" in payload["工作流消息包"]
        assert "负责人：运营负责人A" in payload["工作流执行包"]
        assert payload["套用模板"] == "执行跟进默认模板"
        assert payload["汇报对象"] == "经营会"
        assert payload["拍板负责人"] == "经营拍板人"
        assert payload["执行负责人"] == "运营负责人A"
        assert payload["复核负责人"] == "分析负责人B"
        assert payload["复盘负责人"] == "复盘负责人C"
        assert payload["复核SLA小时"] == 12

    @pytest.mark.asyncio
    async def test_apply_template_config_prefers_explicit_task_template(self, ceo_result):
        rows = [
            {
                "record_id": "rec_tpl_route",
                "fields": {
                    "启用": True,
                    "模板名称": "执行路由通用模板",
                    "适用工作流路由": "直接执行",
                    "适用输出目的": "执行跟进",
                    "汇报模板": "任务：{task_title}\\n对象：{audience}",
                    "执行模板": "负责人：{execution_owner}",
                    "默认拍板负责人": "默认拍板人A",
                    "默认执行负责人": "运营负责人A",
                },
            },
            {
                "record_id": "rec_tpl_exact",
                "fields": {
                    "启用": True,
                    "模板名称": "CEO 专项模板",
                    "适用工作流路由": "等待拍板",
                    "适用输出目的": "管理决策",
                    "汇报模板": "专项任务：{task_title}",
                    "执行模板": "专项执行人：{execution_owner}",
                    "默认拍板负责人": "专项拍板人",
                    "默认执行负责人": "专项负责人",
                },
            },
        ]
        with patch("app.bitable_workflow.scheduler.bitable_ops.list_records", new=AsyncMock(return_value=rows)):
            from app.bitable_workflow.scheduler import _apply_template_config

            payload = await _apply_template_config(
                "app_token",
                "tbl_template",
                "增长复盘任务",
                {"输出目的": "执行跟进", "套用模板": "CEO 专项模板"},
                {"推荐动作": "直接采用"},
                ceo_result,
                {
                    "工作流路由": "直接执行",
                    "工作流消息包": "old-message",
                    "工作流执行包": "old-exec",
                    "汇报对象": "",
                    "执行负责人": "",
                    "复核负责人": "",
                    "复核SLA小时": 0,
                },
            )

        assert payload["工作流消息包"].startswith("专项任务：增长复盘任务")
        assert payload["工作流执行包"].startswith("专项执行人：专项负责人")
        assert payload["套用模板"] == "CEO 专项模板"
        assert payload["拍板负责人"] == "专项拍板人"
        assert payload["执行负责人"] == "专项负责人"


class TestTaskDeliverySnapshot:
    def test_build_task_delivery_snapshot(self):
        analyst = AgentResult(
            agent_id="data_analyst",
            agent_name="数据分析师",
            sections=[ResultSection(title="洞察", content="增长放缓，需拆解渠道结构。")],
            action_items=["补齐渠道漏斗"],
            raw_output="ok",
            structured_evidence=[
                {"claim": "自然流量下滑", "source_type": "real_data", "confidence": "high", "usage": "risk"},
                {"claim": "老用户转介绍占比提升", "source_type": "benchmark", "confidence": "medium", "usage": "opportunity"},
            ],
        )
        ceo = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[ResultSection(title="管理摘要", content="可以先收缩低效渠道，再补数复核。")],
            action_items=["先停掉低 ROI 渠道"],
            raw_output="summary",
            decision_items=[
                {"summary": "补齐渠道归因", "type": "need_data"},
                {"summary": "暂停低 ROI 投放", "type": "execute_now"},
            ],
        )
        review_fields = {
            "推荐动作": "补数后复核",
            "评审摘要": "真实性不足，需补齐归因数据。",
            "真实性": 3,
            "决策性": 4,
            "可执行性": 4,
            "闭环准备度": 3,
            "需补数事项": "- 补齐归因\n- 核验口径",
        }
        from app.bitable_workflow.scheduler import _build_task_delivery_snapshot

        snapshot = _build_task_delivery_snapshot(
            "增长复盘任务",
            {},
            [analyst],
            ceo,
            review_fields,
            evidence_written=5,
        )

        assert snapshot["最新评审动作"] == "补数后复核"
        assert snapshot["证据条数"] == 5
        assert snapshot["高置信证据数"] == 1
        assert snapshot["硬证据数"] == 1
        assert snapshot["待验证证据数"] == 0
        assert snapshot["进入CEO汇总证据数"] == 2
        assert snapshot["决策事项数"] == 2
        assert snapshot["需补数条数"] == 2
        assert snapshot["汇报就绪度"] == 4
        assert snapshot["工作流路由"] == "补数复核"
        assert snapshot["业务归属"] == "综合经营"
        assert snapshot["汇报对象级别"] == "负责人"
        assert snapshot["待安排复核"] is True
        assert snapshot["当前责任角色"] == "复核人"
        assert snapshot["当前原生动作"] == "安排复核"
        assert snapshot["异常状态"] == "需关注"
        assert snapshot["异常类型"] == "责任人待指派"
        assert snapshot["自动化执行状态"] == "执行中"
        assert "增长复盘任务" in snapshot["工作流消息包"]


class TestWorkflowPayload:
    def test_waiting_approval_route_does_not_mark_execution_queue(self):
        ceo = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[ResultSection(title="管理摘要", content="先等管理层拍板，再安排执行。")],
            action_items=[],
            raw_output="summary",
            decision_items=[
                {"summary": "批准 Q3 预算追加", "type": "ceo_decision"},
                {"summary": "通知销售团队跟进重点客户", "type": "execute_now"},
            ],
        )
        from app.bitable_workflow.scheduler import _build_workflow_payload

        payload = _build_workflow_payload("经营复盘", {}, None, ceo)

        assert payload["工作流路由"] == "等待拍板"
        assert payload["待拍板确认"] is True
        assert payload["待创建执行任务"] is False
        assert payload["待执行确认"] is False

    def test_route_transition_back_to_waiting_approval_clears_recheck_deadline(self):
        ceo = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[ResultSection(title="管理摘要", content="补数后已恢复可拍板状态。")],
            action_items=[],
            raw_output="summary",
            decision_items=[{"summary": "确认渠道预算调整", "type": "ceo_decision"}],
        )
        from app.bitable_workflow.scheduler import _build_workflow_payload

        payload = _build_workflow_payload(
            "异常回流任务",
            {
                "工作流路由": "补数复核",
                "待安排复核": True,
                "建议复核时间": 1893456000000,
                "执行截止时间": 1893542400000,
            },
            {"推荐动作": ""},
            ceo,
        )

        assert payload["工作流路由"] == "等待拍板"
        assert payload["待安排复核"] is False
        assert payload["待拍板确认"] is True
        assert payload["建议复核时间"] is None
        assert payload["执行截止时间"] is None

    def test_route_transition_to_direct_report_clears_stale_execution_and_review_flags(self):
        ceo = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[ResultSection(title="管理摘要", content="当前无需拍板和执行，直接同步结论。")],
            action_items=[],
            raw_output="summary",
            decision_items=[],
        )
        from app.bitable_workflow.scheduler import _build_workflow_payload

        payload = _build_workflow_payload(
            "直接汇报任务",
            {
                "工作流路由": "重新分析",
                "待安排复核": True,
                "待执行确认": True,
                "建议复核时间": 1893456000000,
                "执行截止时间": 1893542400000,
            },
            {"推荐动作": ""},
            ceo,
        )

        assert payload["工作流路由"] == "直接汇报"
        assert payload["待发送汇报"] is True
        assert payload["待安排复核"] is False
        assert payload["待执行确认"] is False
        assert payload["建议复核时间"] is None
        assert payload["执行截止时间"] is None

    def test_route_transition_to_direct_execute_preserves_existing_due_time(self):
        ceo = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[ResultSection(title="管理摘要", content="已有明确执行截止时间，继续推进执行。")],
            action_items=[],
            raw_output="summary",
            decision_items=[{"summary": "安排销售团队跟进", "type": "execute_now"}],
        )
        from app.bitable_workflow.scheduler import _build_workflow_payload

        payload = _build_workflow_payload(
            "执行任务",
            {
                "执行截止时间": 1893542400000,
            },
            {"推荐动作": ""},
            ceo,
        )

        assert payload["工作流路由"] == "直接执行"
        assert payload["待执行确认"] is True
        assert payload["执行截止时间"] == 1893542400000


class TestRunCycleActionRouting:
    @pytest.mark.asyncio
    async def test_run_cycle_passes_action_table_and_route_to_delivery_helpers(self):
        pending_record = {
            "record_id": "rec_task_1",
            "fields": {
                "任务标题": "增长复盘任务",
                "状态": Status.PENDING,
                "优先级": "P1 高",
                "任务编号": "12",
            },
        }
        claim_record = {
            "record_id": "rec_task_1",
            "fields": {
                "任务标题": "增长复盘任务",
                "状态": Status.ANALYZING,
                "优先级": "P1 高",
                "任务编号": "12",
                "背景说明": "分析最近两周增长放缓原因",
            },
        }
        analyst = AgentResult(
            agent_id="data_analyst",
            agent_name="数据分析师",
            sections=[ResultSection(title="洞察", content="渠道转化下滑")],
            action_items=[],
            raw_output="ok",
        )
        ceo = AgentResult(
            agent_id="ceo_assistant",
            agent_name="CEO 助理",
            sections=[ResultSection(title="管理摘要", content="需要先补数再复核")],
            action_items=[],
            raw_output="summary",
        )

        async def fake_list_records(_app_token, _table_id, filter_expr=None, **_kwargs):
            if Status.ANALYZING in (filter_expr or ""):
                return []
            if Status.PENDING in (filter_expr or ""):
                return [pending_record]
            return []

        with ExitStack() as stack:
            stack.enter_context(patch("app.bitable_workflow.scheduler.USE_RECORDS_SEARCH", False))
            stack.enter_context(patch("app.bitable_workflow.scheduler.USE_BATCH_RECORDS", False))
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.bitable_ops.list_records", side_effect=fake_list_records)
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler._build_dep_index", new=AsyncMock(return_value={}))
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler._claim_pending_record", new=AsyncMock(return_value=claim_record))
            )
            stack.enter_context(
                patch(
                    "app.bitable_workflow.scheduler._hydrate_task_dataset_reference",
                    new=AsyncMock(side_effect=lambda *args: args[-1]),
                )
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.run_task_pipeline", new=AsyncMock(return_value=([analyst], ceo)))
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.collect_prior_task_output_ids", new=AsyncMock(return_value=[]))
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.write_agent_outputs", new=AsyncMock(return_value=1))
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.write_evidence_records", new=AsyncMock(return_value=4))
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.write_ceo_report", new=AsyncMock())
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.update_performance", new=AsyncMock())
            )
            stack.enter_context(
                patch(
                    "app.bitable_workflow.scheduler.write_review_record",
                    new=AsyncMock(return_value={"fields": {"推荐动作": "补数后复核"}}),
                )
            )
            stack.enter_context(
                patch(
                    "app.bitable_workflow.scheduler._build_task_delivery_snapshot",
                    return_value={
                        "工作流路由": "补数复核",
                        "工作流消息包": "msg",
                        "证据条数": 4,
                        "高置信证据数": 2,
                        "硬证据数": 1,
                        "待验证证据数": 1,
                        "决策事项数": 0,
                        "需补数条数": 1,
                    },
                )
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.cleanup_prior_task_output_ids", new=AsyncMock())
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.bitable_ops.update_record_optional_fields", new=AsyncMock())
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler.bitable_ops.update_record", new=AsyncMock())
            )
            stack.enter_context(
                patch("app.bitable_workflow.scheduler._write_action_record", new=AsyncMock())
            )
            mock_review_history = stack.enter_context(
                patch("app.bitable_workflow.scheduler._write_review_history_record", new=AsyncMock(return_value={"record_id": "rec_hist", "round": 1}))
            )
            mock_archive = stack.enter_context(
                patch("app.bitable_workflow.scheduler._write_delivery_archive_record", new=AsyncMock(return_value={"record_id": "rec_arc", "version": "v1", "archive_status": "待复核"}))
            )
            mock_automation_log = stack.enter_context(
                patch("app.bitable_workflow.scheduler._write_automation_log", new=AsyncMock())
            )
            mock_send = stack.enter_context(
                patch("app.bitable_workflow.scheduler._send_completion_message", new=AsyncMock())
            )
            mock_followup = stack.enter_context(
                patch("app.bitable_workflow.scheduler._create_followup_tasks", new=AsyncMock())
            )
            mock_recheck = stack.enter_context(
                patch("app.bitable_workflow.scheduler._create_review_recheck_task", new=AsyncMock())
            )
            stack.enter_context(
                patch("app.bitable_workflow.progress_broker.publish", new=AsyncMock())
            )
            stack.enter_context(
                patch("app.bitable_workflow.agent_cache.invalidate_task_cache", new=AsyncMock())
            )
            from app.bitable_workflow.scheduler import _run_one_cycle_locked

            processed = await _run_one_cycle_locked("app_token", TABLE_IDS)

        assert processed == 1
        assert mock_review_history.await_args.args[1] == "tbl_review_history"
        assert mock_archive.await_args.args[1] == "tbl_archive"
        assert mock_automation_log.await_count >= 2
        assert mock_send.await_args.kwargs["action_tid"] == "tbl_action"
        assert mock_send.await_args.kwargs["automation_log_tid"] == "tbl_automation_log"
        assert mock_send.await_args.kwargs["route"] == "补数复核"
        assert mock_followup.await_args.kwargs["action_tid"] == "tbl_action"
        assert mock_followup.await_args.kwargs["automation_log_tid"] == "tbl_automation_log"
        assert mock_followup.await_args.kwargs["route"] == "补数复核"
        assert mock_recheck.await_args.kwargs["action_tid"] == "tbl_action"
        assert mock_recheck.await_args.kwargs["automation_log_tid"] == "tbl_automation_log"
        assert mock_recheck.await_args.kwargs["route"] == "补数复核"
