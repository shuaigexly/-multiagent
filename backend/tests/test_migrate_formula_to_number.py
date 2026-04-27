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
        """v8.6.20-r6：先建影子字段 → 回填影子 → 删旧 → rename 影子。
        若中途 _create_number_field 失败也不会丢原 Formula 字段。"""
        records = [
            {"record_id": "r1", "fields": {"优先级": "P0 紧急"}},
            {"record_id": "r2", "fields": {"优先级": "P1 高"}},
            {"record_id": "r3", "fields": {"优先级": [{"text": "P2 中", "type": "text"}]}},
            {"record_id": "r4", "fields": {"优先级": ""}},
        ]
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field", new=AsyncMock()) as mock_del, \
             patch.object(mig, "_create_number_field", new=AsyncMock(return_value="fid_new")) as mock_create, \
             patch.object(mig, "_rename_field", new=AsyncMock(return_value="fid_new")) as mock_rename, \
             patch("app.bitable_workflow.bitable_ops.list_records", new=AsyncMock(return_value=records)), \
             patch("app.bitable_workflow.bitable_ops.update_record", new=AsyncMock()) as mock_update:
            res = await mig.migrate_one(
                "app", "分析任务", "综合评分", "优先级", priority_score, dry_run=False,
            )

        assert res["old_field_id"] == "fid_old"
        assert res["new_field_id"] == "fid_new"
        assert res["backfilled"] == 4
        assert res.get("failed_record_ids") == []
        mock_create.assert_called_once()  # 建影子
        mock_del.assert_called_once()  # 删旧 Formula
        mock_rename.assert_called_once()  # rename 影子 → 目标名
        # 回填写到影子字段名（rename 前），而非最终名
        calls = mock_update.call_args_list
        assert len(calls) == 4
        scores_written = [c.args[3]["综合评分__migrating"] for c in calls]
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
             patch.object(mig, "_rename_field", new=AsyncMock(return_value="fid_new")), \
             patch("app.bitable_workflow.bitable_ops.list_records", new=AsyncMock(return_value=records)), \
             patch("app.bitable_workflow.bitable_ops.update_record", new=AsyncMock()) as mock_update:
            res = await mig.migrate_one(
                "app", "岗位分析", "健康度数值", "健康度评级", health_score, dry_run=False,
            )
        assert res["backfilled"] == 3
        # 写到影子字段名「健康度数值__migrating」
        scores = [c.args[3]["健康度数值__migrating"] for c in mock_update.call_args_list]
        assert scores == [100, 60, 20]

    @pytest.mark.asyncio
    async def test_create_failure_does_not_delete_original_formula(self):
        """v8.6.20-r6 关键防回归：若 _create_number_field 抛错，原 Formula 字段
        必须完整保留（不删、不变）。"""
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field", new=AsyncMock()) as mock_del, \
             patch.object(mig, "_create_number_field", new=AsyncMock(side_effect=RuntimeError("CREATE failed"))), \
             patch.object(mig, "_rename_field", new=AsyncMock()) as mock_rename, \
             patch("app.bitable_workflow.bitable_ops.update_record", new=AsyncMock()) as mock_update:
            with pytest.raises(RuntimeError, match="CREATE failed"):
                await mig.migrate_one(
                    "app", "分析任务", "综合评分", "优先级", priority_score, dry_run=False,
                )
        mock_del.assert_not_called()  # 没动旧字段
        mock_rename.assert_not_called()
        mock_update.assert_not_called()  # 也没回填

    @pytest.mark.asyncio
    async def test_rename_failure_after_delete_returns_issues_not_raises(self):
        """v8.6.20-r7（审计 #4）：DELETE 已成功 + RENAME 失败时，返回带 issues 的状态
        而不是 raise，保留影子字段供用户手工救场。否则旧 Formula 已删 + 影子未改名
        → schema 永久不一致（综合评分不存在 + 综合评分__migrating 残留）。"""
        records = [{"record_id": "r1", "fields": {"优先级": "P1 高"}}]
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field", new=AsyncMock()) as mock_del, \
             patch.object(mig, "_create_number_field", new=AsyncMock(return_value="fid_shadow")), \
             patch.object(mig, "_rename_field", new=AsyncMock(side_effect=RuntimeError("PUT 91402 NOTEXIST"))) as mock_rename, \
             patch("app.bitable_workflow.bitable_ops.list_records", new=AsyncMock(return_value=records)), \
             patch("app.bitable_workflow.bitable_ops.update_record", new=AsyncMock()):
            res = await mig.migrate_one(
                "app", "分析任务", "综合评分", "优先级", priority_score, dry_run=False,
            )
        # 不再 raise，返回 issues
        assert res.get("issues")
        assert "RENAME 失败" in res["issues"][0]
        assert res.get("shadow_field_id") == "fid_shadow"
        assert res.get("old_field_id") == "fid_old"
        # DELETE 已经发生
        mock_del.assert_called_once()
        # RENAME 已经尝试
        mock_rename.assert_called_once()

    @pytest.mark.asyncio
    async def test_high_failure_rate_keeps_old_field(self):
        """v8.6.20-r6 防回归：回填失败率 > 50% 时保留旧字段 + 影子，不 rename。"""
        records = [
            {"record_id": f"r{i}", "fields": {"优先级": "P1 高"}} for i in range(4)
        ]
        # 4 个全失败
        async def fake_update(*args, **kwargs):
            raise RuntimeError("write failed")
        with patch.object(mig, "_list_table_id", return_value="tbl_x"), \
             patch.object(mig, "_list_fields", return_value=[
                 {"field_name": "综合评分", "type": 20, "field_id": "fid_old"}
             ]), \
             patch.object(mig, "_delete_field", new=AsyncMock()) as mock_del, \
             patch.object(mig, "_create_number_field", new=AsyncMock(return_value="fid_new")), \
             patch.object(mig, "_rename_field", new=AsyncMock()) as mock_rename, \
             patch("app.bitable_workflow.bitable_ops.list_records", new=AsyncMock(return_value=records)), \
             patch("app.bitable_workflow.bitable_ops.update_record", side_effect=fake_update):
            res = await mig.migrate_one(
                "app", "分析任务", "综合评分", "优先级", priority_score, dry_run=False,
            )
        assert res.get("backfilled") == 0
        assert len(res.get("failed_record_ids") or []) == 4
        assert res.get("issues")
        mock_del.assert_not_called()  # 旧字段保留
        mock_rename.assert_not_called()
