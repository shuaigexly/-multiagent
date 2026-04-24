"""内容运营虚拟组织 — 多维表格结构常量（七岗多智能体版）"""

TEXT_FIELD_TYPE = 1
NUMBER_FIELD_TYPE = 2
SINGLE_SELECT_FIELD_TYPE = 3
LINKED_RECORD_FIELD_TYPE = 18  # 关联记录字段（type=18），用于表间关系

TABLE_TASK = "分析任务"
TABLE_AGENT_OUTPUT = "岗位分析"
TABLE_REPORT = "综合报告"
TABLE_PERFORMANCE = "数字员工效能"


class Status:
    PENDING = "待分析"
    ANALYZING = "分析中"
    COMPLETED = "已完成"
    ARCHIVED = "已归档"


ALL_STATUSES = [Status.PENDING, Status.ANALYZING, Status.COMPLETED, Status.ARCHIVED]

ANALYSIS_DIMENSIONS = ["内容战略", "数据复盘", "增长优化", "产品规划", "运营诊断", "综合分析"]

# 分析任务表字段（主表，无关联字段）
TASK_FIELDS = [
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "分析维度",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "options": ANALYSIS_DIMENSIONS,
    },
    {"field_name": "状态", "type": SINGLE_SELECT_FIELD_TYPE, "options": ALL_STATUSES},
    {"field_name": "当前阶段", "type": TEXT_FIELD_TYPE},
    {"field_name": "背景说明", "type": TEXT_FIELD_TYPE},
    {"field_name": "创建时间", "type": TEXT_FIELD_TYPE},
    {"field_name": "完成时间", "type": TEXT_FIELD_TYPE},
]


def agent_output_fields(task_table_id: str) -> list[dict]:
    """岗位分析表字段，通过关联字段（type=18）与分析任务表建立表间关系。

    task_table_id: 分析任务表的 table_id，运行时由 setup_workflow 传入。
    """
    return [
        {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},  # 主字段（Bitable 默认）
        {
            "field_name": "关联任务",
            "type": LINKED_RECORD_FIELD_TYPE,
            "table_id": task_table_id,
        },
        {"field_name": "岗位角色", "type": TEXT_FIELD_TYPE},
        {"field_name": "分析摘要", "type": TEXT_FIELD_TYPE},
        {"field_name": "行动项", "type": TEXT_FIELD_TYPE},
        {"field_name": "分析思路", "type": TEXT_FIELD_TYPE},
        {"field_name": "图表数据", "type": TEXT_FIELD_TYPE},
        {"field_name": "生成时间", "type": TEXT_FIELD_TYPE},
    ]


def report_fields(task_table_id: str) -> list[dict]:
    """综合报告表字段，通过关联字段（type=18）与分析任务表建立表间关系。

    task_table_id: 分析任务表的 table_id，运行时由 setup_workflow 传入。
    """
    return [
        {"field_name": "报告标题", "type": TEXT_FIELD_TYPE},  # 主字段（Bitable 默认）
        {
            "field_name": "关联任务",
            "type": LINKED_RECORD_FIELD_TYPE,
            "table_id": task_table_id,
        },
        {"field_name": "核心结论", "type": TEXT_FIELD_TYPE},
        {"field_name": "重要机会", "type": TEXT_FIELD_TYPE},
        {"field_name": "重要风险", "type": TEXT_FIELD_TYPE},
        {"field_name": "CEO决策事项", "type": TEXT_FIELD_TYPE},
        {"field_name": "管理摘要", "type": TEXT_FIELD_TYPE},
        {"field_name": "参与岗位数", "type": NUMBER_FIELD_TYPE},
        {"field_name": "生成时间", "type": TEXT_FIELD_TYPE},
    ]


PERFORMANCE_FIELDS = [
    {"field_name": "员工姓名", "type": TEXT_FIELD_TYPE},
    {"field_name": "角色", "type": TEXT_FIELD_TYPE},
    {"field_name": "处理任务数", "type": NUMBER_FIELD_TYPE},
    {"field_name": "更新时间", "type": TEXT_FIELD_TYPE},
]

# 初始种子任务: (标题, 分析维度, 背景说明)
SEED_TASKS = [
    (
        "AI 产品内容战略分析",
        "内容战略",
        "分析当前 AI 工具类产品的内容运营策略，识别差异化机会，规划内容资产布局",
    ),
    (
        "内容运营核心指标复盘",
        "数据复盘",
        "复盘近期内容产出、分发、转化各环节关键指标，识别瓶颈并提出改进方向",
    ),
    (
        "SEO 增长机会全景扫描",
        "增长优化",
        "分析行业关键词机会、内容缺口，规划 SEO 驱动的自然流量增长路径",
    ),
    (
        "内容产品功能路线图规划",
        "产品规划",
        "梳理内容创作与分发产品功能需求，制定优先级与 MVP 计划，对齐业务目标",
    ),
]
