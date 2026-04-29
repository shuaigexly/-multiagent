"""测试多维表格结构定义（schema.py）"""
import pytest
from app.bitable_workflow.schema import (
    ACTION_FIELDS,
    AUTOMATION_LOG_FIELDS,
    DELIVERY_ARCHIVE_FIELDS,
    REVIEW_HISTORY_FIELDS,
    TEMPLATE_CENTER_FIELDS,
    TEXT_FIELD_TYPE,
    NUMBER_FIELD_TYPE,
    SINGLE_SELECT_FIELD_TYPE,
    LINKED_RECORD_FIELD_TYPE,
    TASK_FIELDS,
    PERFORMANCE_FIELDS,
    EVIDENCE_FIELDS,
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
        assert "任务来源" in names
        assert "业务归属" in names
        assert "最新评审动作" in names
        assert "汇报就绪度" in names
        assert "证据条数" in names
        assert "硬证据数" in names
        assert "待验证证据数" in names
        assert "工作流路由" in names
        assert "套用模板" in names
        assert "待发送汇报" in names
        assert "建议复核时间" in names
        assert "汇报版本号" in names
        assert "归档状态" in names
        assert "汇报对象级别" in names
        assert "拍板负责人" in names
        assert "执行负责人" in names
        assert "复核负责人" in names
        assert "复盘负责人" in names
        assert "当前责任角色" in names
        assert "当前责任人" in names
        assert "当前原生动作" in names
        assert "异常状态" in names
        assert "异常类型" in names
        assert "异常说明" in names
        assert "自动化执行状态" in names
        assert "是否已拍板" in names
        assert "待拍板确认" in names
        assert "拍板时间" in names
        assert "是否已执行落地" in names
        assert "待执行确认" in names
        assert "执行完成时间" in names
        assert "是否进入复盘" in names
        assert "待复盘确认" in names

    def test_agent_output_required_columns(self):
        fields = agent_output_fields("tbl_x")
        names = {f["field_name"] for f in fields}
        assert "任务标题" in names  # v8.6.1: 主字段，文本逻辑关联
        assert "岗位角色" in names
        assert "分析摘要" in names

    def test_evidence_required_columns(self):
        names = {f["field_name"] for f in EVIDENCE_FIELDS}
        assert "证据标题" in names
        assert "证据等级" in names
        assert "证据置信度" in names

    def test_action_required_columns(self):
        names = {f["field_name"] for f in ACTION_FIELDS}
        assert "动作标题" in names
        assert "任务标题" in names
        assert "动作类型" in names
        assert "动作状态" in names
        assert "工作流路由" in names
        assert "动作内容" in names
        assert "执行结果" in names
        assert "关联记录ID" in names

    def test_automation_log_required_columns(self):
        names = {f["field_name"] for f in AUTOMATION_LOG_FIELDS}
        assert "日志标题" in names
        assert "任务标题" in names
        assert "节点名称" in names
        assert "执行状态" in names
        assert "日志摘要" in names

    def test_automation_log_status_supports_running_agent_nodes(self):
        status_field = next(f for f in AUTOMATION_LOG_FIELDS if f["field_name"] == "执行状态")
        option_names = {option["name"] for option in status_field["options"]}
        assert "执行中" in option_names

    def test_review_history_required_columns(self):
        names = {f["field_name"] for f in REVIEW_HISTORY_FIELDS}
        assert "复核标题" in names
        assert "任务标题" in names
        assert "复核轮次" in names
        assert "推荐动作" in names
        assert "新旧结论差异" in names

    def test_delivery_archive_required_columns(self):
        names = {f["field_name"] for f in DELIVERY_ARCHIVE_FIELDS}
        assert "归档标题" in names
        assert "任务标题" in names
        assert "汇报版本号" in names
        assert "归档状态" in names
        assert "最新评审动作" in names
        assert "一句话结论" in names

    def test_template_center_required_columns(self):
        names = {f["field_name"] for f in TEMPLATE_CENTER_FIELDS}
        assert "模板名称" in names
        assert "适用工作流路由" in names
        assert "汇报模板" in names
        assert "执行模板" in names
        assert "默认拍板负责人" in names
        assert "默认复盘负责人" in names
        assert "启用" in names

    def test_report_required_columns(self):
        fields = report_fields("tbl_x")
        names = {f["field_name"] for f in fields}
        assert "报告标题" in names  # v8.6.1: 主字段，文本逻辑关联
        assert "一句话结论" in names
        assert "核心结论" in names
        assert "CEO决策事项" in names
        assert "高管一页纸" in names


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

    def test_archive_status_field_includes_retrospective_stage(self):
        archive_field = next(f for f in TASK_FIELDS if f["field_name"] == "归档状态")
        raw_options = archive_field.get("options") or archive_field.get("property", {}).get("options", [])
        options = [item["name"] if isinstance(item, dict) else item for item in raw_options]
        assert "待汇报" in options
        assert "待拍板" in options
        assert "待执行" in options
        assert "待复盘" in options
        assert "待复核" in options
        assert "已归档" in options


class TestSeedData:
    def test_seed_tasks_count(self):
        assert len(SEED_TASKS) >= 4, "至少应有 4 条种子任务覆盖核心分析维度"

    def test_seed_tasks_format(self):
        for task in SEED_TASKS:
            assert len(task) == 4, "v8.6.5 种子任务格式：(标题, 分析维度, 背景说明, 数据源)"
            title, dimension, background, data_source = task
            assert title and dimension and background and data_source

    def test_seed_tasks_dimensions_valid(self):
        for _, dimension, _, _ in SEED_TASKS:
            assert dimension in ANALYSIS_DIMENSIONS, f"维度 {dimension!r} 不在合法值列表中"

    def test_datasets_metadata_complete(self):
        """v8.6.16：DATASETS 每行 4-tuple，CSV 至少 3 行（表头+2 数据行），描述非空。"""
        from app.bitable_workflow.demo_data import DATASETS, csv_to_markdown
        assert len(DATASETS) >= 7, "至少 7 条数据集覆盖 InsightHub 全场景"
        for name, dtype, doc, csv in DATASETS:
            assert name and dtype and doc and csv
            lines = [ln for ln in csv.strip().splitlines() if ln.strip()]
            assert len(lines) >= 3, f"{name} 数据集行数过少"
            md = csv_to_markdown(csv)
            assert "|" in md and "---" in md, f"{name} markdown 转换失败"

    def test_csv_to_markdown_basic(self):
        from app.bitable_workflow.demo_data import csv_to_markdown
        out = csv_to_markdown("a,b,c\n1,2,3\n4,5,6")
        assert out.startswith("| a | b | c |")
        assert "| --- | --- | --- |" in out
        assert "| 1 | 2 | 3 |" in out

    def test_seed_tasks_have_real_data_source(self):
        """v8.6.5：每个 SEED 必须带可解析的数据源（CSV/markdown/json），否则 6 个 agent
        全部基于背景说明跑空，输出"内容干巴巴"。
        """
        for title, _, _, data_source in SEED_TASKS:
            # 至少要有数字或 CSV 分隔符，避免纯文字任务说明误判为"数据源"
            assert any(c.isdigit() for c in data_source), \
                f"{title} 数据源里没数字，等于没数据"
            assert "," in data_source or "|" in data_source or "\n" in data_source, \
                f"{title} 数据源不是结构化数据"
