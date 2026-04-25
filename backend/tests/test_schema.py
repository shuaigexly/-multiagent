"""测试多维表格结构定义（schema.py）"""
import pytest
from app.bitable_workflow.schema import (
    TEXT_FIELD_TYPE,
    NUMBER_FIELD_TYPE,
    SINGLE_SELECT_FIELD_TYPE,
    LINKED_RECORD_FIELD_TYPE,
    TASK_FIELDS,
    PERFORMANCE_FIELDS,
    agent_output_fields,
    report_fields,
    Status,
    SEED_TASKS,
    ANALYSIS_DIMENSIONS,
)


class TestLinkedRecordFields:
    """v8.6.1：飞书 records 写接口（POST/PUT/batch_create）实测全部不接受
    LinkedRecord(type=18) 字段写入，属于 Feishu Bitable 平台硬限制。
    schema 中已删除「关联任务」字段，改用任务标题文本字段做逻辑关联。"""

    def test_agent_output_fields_no_linked_record(self):
        fields = agent_output_fields("tbl_abc123")
        linked = [f for f in fields if f["type"] == LINKED_RECORD_FIELD_TYPE]
        assert len(linked) == 0, "v8.6.1: 飞书 API 限制，不再创建 LinkedRecord 字段"

    def test_report_fields_no_linked_record(self):
        fields = report_fields("tbl_xyz789")
        linked = [f for f in fields if f["type"] == LINKED_RECORD_FIELD_TYPE]
        assert len(linked) == 0, "v8.6.1: 飞书 API 限制，不再创建 LinkedRecord 字段"

    def test_task_fields_has_no_linked_record(self):
        """分析任务表是主表，不应有关联字段"""
        linked = [f for f in TASK_FIELDS if f.get("type") == LINKED_RECORD_FIELD_TYPE]
        assert len(linked) == 0

    def test_performance_fields_has_no_linked_record(self):
        linked = [f for f in PERFORMANCE_FIELDS if f.get("type") == LINKED_RECORD_FIELD_TYPE]
        assert len(linked) == 0

    def test_task_table_id_param_still_accepted(self):
        """task_table_id 参数保留以兼容 setup_workflow 调用签名（即使不再使用）。"""
        fields_a = agent_output_fields("tbl_a")
        fields_b = agent_output_fields("tbl_b")
        # 字段结构相同（task_table_id 不再影响输出）
        names_a = [f["field_name"] for f in fields_a]
        names_b = [f["field_name"] for f in fields_b]
        assert names_a == names_b


class TestPrimaryField:
    """Feishu Bitable 主字段必须是文本类型，create_table 会将第一个字段重命名为主字段"""

    def test_task_fields_primary_is_text(self):
        assert TASK_FIELDS[0]["type"] == TEXT_FIELD_TYPE

    def test_agent_output_primary_is_text(self):
        fields = agent_output_fields("tbl_x")
        assert fields[0]["type"] == TEXT_FIELD_TYPE, "主字段必须是文本类型"

    def test_report_primary_is_text(self):
        fields = report_fields("tbl_x")
        assert fields[0]["type"] == TEXT_FIELD_TYPE, "主字段必须是文本类型"

    def test_performance_primary_is_text(self):
        assert PERFORMANCE_FIELDS[0]["type"] == TEXT_FIELD_TYPE


class TestFieldCompleteness:
    def test_task_fields_required_columns(self):
        names = {f["field_name"] for f in TASK_FIELDS}
        assert "任务标题" in names
        assert "状态" in names
        assert "分析维度" in names
        assert "创建时间" in names

    def test_agent_output_required_columns(self):
        fields = agent_output_fields("tbl_x")
        names = {f["field_name"] for f in fields}
        assert "任务标题" in names  # v8.6.1: 主字段，文本逻辑关联
        assert "岗位角色" in names
        assert "分析摘要" in names

    def test_report_required_columns(self):
        fields = report_fields("tbl_x")
        names = {f["field_name"] for f in fields}
        assert "报告标题" in names  # v8.6.1: 主字段，文本逻辑关联
        assert "核心结论" in names
        assert "CEO决策事项" in names


class TestStatusMachine:
    def test_all_statuses_defined(self):
        assert Status.PENDING == "待分析"
        assert Status.ANALYZING == "分析中"
        assert Status.COMPLETED == "已完成"
        assert Status.ARCHIVED == "已归档"

    def test_status_field_includes_all_statuses(self):
        status_field = next(f for f in TASK_FIELDS if f["field_name"] == "状态")
        raw_options = status_field.get("options") or status_field.get("property", {}).get("options", [])
        options = [item["name"] if isinstance(item, dict) else item for item in raw_options]
        assert Status.PENDING in options
        assert Status.ANALYZING in options
        assert Status.COMPLETED in options
        assert Status.ARCHIVED in options


class TestSeedData:
    def test_seed_tasks_count(self):
        assert len(SEED_TASKS) >= 4, "至少应有 4 条种子任务覆盖核心分析维度"

    def test_seed_tasks_format(self):
        for task in SEED_TASKS:
            assert len(task) == 3, "种子任务格式：(标题, 分析维度, 背景说明)"
            title, dimension, background = task
            assert title and dimension and background

    def test_seed_tasks_dimensions_valid(self):
        for _, dimension, _ in SEED_TASKS:
            assert dimension in ANALYSIS_DIMENSIONS, f"维度 {dimension!r} 不在合法值列表中"
