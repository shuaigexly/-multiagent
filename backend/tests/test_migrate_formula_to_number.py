"""测试 v8.6.20-r4 Formula(20) → Number(2) 字段迁移工具。"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.bitable_workflow import migrate_formula_to_number as mig
from app.bitable_workflow.schema import priority_score, health_score


class TestFlatten:
    def test_str_passthrough(self):
        assert mig._flatten("P1 高") == "P1 高"

    def test_list_richtext_flatten(self):
        v = [{"text": "P0", "type": "text"}, {"text": " 紧急", "type": "text"}]
        assert mig._flatten(v) == "P0 紧急"

    def test_none(self):
        assert mig._flatten(None) == ""


class TestMigrateOne:
    @pytest.mark.asyncio
    async def test_skip_when_already_number(self):
        """字段已是 Number(2) → 跳过，不删不建。"""
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 2, "field_id": "fid"}
             ]):
            res = await mig.migrate_one("app", "分析任务", "综合评分", "优先级", priority_score)
        assert res["skipped"] is True
        assert "已是 Number" in res["reason"]

    @pytest.mark.asyncio
    async def test_skip_when_field_missing(self):
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[]):
            res = await mig.migrate_one("app", "分析任务", "综合评分", "优先级", priority_score)
        assert res["skipped"] is True

    @pytest.mark.asyncio
    async def test_skip_when_table_missing(self):
        with patch.object(mig, "_list_table_id", return_value=None):
            res = await mig.migrate_one("app", "幽灵表", "x", "y", priority_score)
        assert res["skipped"] is True
        assert "table 不存在" in res["reason"]

    @pytest.mark.asyncio
    async def test_skip_when_other_type(self):
        """字段是 SingleSelect(3) 等其他类型 → 不处理（避免误删）。"""
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 3, "field_id": "fid"}
             ]):
            res = await mig.migrate_one("app", "分析任务", "综合评分", "优先级", priority_score)
        assert res["skipped"] is True
        assert "类型=3" in res["reason"]

    @pytest.mark.asyncio
    async def test_dry_run_no_writes(self):
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field") as mock_del, \
             patch.object(mig, "_create_number_field") as mock_create, \
             patch("app.bitable_workflow.bitable_ops.update_record") as mock_update:
            res = await mig.migrate_one(
                "app", "分析任务", "综合评分", "优先级", priority_score, dry_run=True,
            )
        assert res.get("dry_run") is True
        assert not mock_del.called
        assert not mock_create.called
        assert not mock_update.called

    @pytest.mark.asyncio
    async def test_full_migration_path(self):
        """Formula(20) 字段 → 删除 → 重建 Number → 回填 priority_score 值。"""
        records = [
            {"record_id": "r1", "fields": {"优先级": "P0 紧急"}},
            {"record_id": "r2", "fields": {"优先级": "P1 高"}},
            {"record_id": "r3", "fields": {"优先级": [{"text": "P2 中", "type": "text"}]}},
            {"record_id": "r4", "fields": {"优先级": ""}},  # 缺省 → 25
        ]
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field", new=AsyncMock()) as mock_del, \
             patch.object(mig, "_create_number_field", new=AsyncMock(return_value="fid_new")) as mock_create, \
             patch("app.bitable_workflow.bitable_ops.list_records", new=AsyncMock(return_value=records)), \
             patch("app.bitable_workflow.bitable_ops.update_record", new=AsyncMock()) as mock_update:
            res = await mig.migrate_one(
                "app", "分析任务", "综合评分", "优先级", priority_score, dry_run=False,
            )

        assert res["old_field_id"] == "fid_old"
        assert res["new_field_id"] == "fid_new"
        assert res["backfilled"] == 4
        mock_del.assert_called_once()
        mock_create.assert_called_once()
        # 4 次回填：100/75/50/25
        calls = mock_update.call_args_list
        assert len(calls) == 4
        scores_written = [c.args[3]["综合评分"] for c in calls]
        assert scores_written == [100, 75, 50, 25]

    @pytest.mark.asyncio
    async def test_health_score_path(self):
        """另一组合：健康度数值 ← health_score(健康度评级)。"""
        records = [
            {"record_id": "r1", "fields": {"健康度评级": "🟢 健康"}},
            {"record_id": "r2", "fields": {"健康度评级": "🟡 关注"}},
            {"record_id": "r3", "fields": {"健康度评级": "🔴 预警"}},
        ]
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "健康度数值", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field", new=AsyncMock()), \
             patch.object(mig, "_create_number_field", new=AsyncMock(return_value="fid_new")), \
             patch("app.bitable_workflow.bitable_ops.list_records", new=AsyncMock(return_value=records)), \
             patch("app.bitable_workflow.bitable_ops.update_record", new=AsyncMock()) as mock_update:
            res = await mig.migrate_one(
                "app", "岗位分析", "健康度数值", "健康度评级", health_score, dry_run=False,
            )
        assert res["backfilled"] == 3
        scores = [c.args[3]["健康度数值"] for c in mock_update.call_args_list]
        assert scores == [100, 60, 20]
