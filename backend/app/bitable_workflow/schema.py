"""内容运营虚拟组织 — 多维表格结构常量"""

TEXT_FIELD_TYPE = 1
NUMBER_FIELD_TYPE = 2
SINGLE_SELECT_FIELD_TYPE = 3

TABLE_CONTENT = "内容任务"
TABLE_PERFORMANCE = "员工效能"
TABLE_REPORT = "周报"


class Status:
    PENDING_TOPIC = "待选题"
    WRITING = "写作中"
    PENDING_REVIEW = "待审核"
    APPROVED = "审核通过"
    REJECTED = "审核拒绝"
    PUBLISHED = "已发布"
    ANALYZED = "已分析"


_ALL_STATUSES = [
    Status.PENDING_TOPIC,
    Status.WRITING,
    Status.PENDING_REVIEW,
    Status.APPROVED,
    Status.REJECTED,
    Status.PUBLISHED,
    Status.ANALYZED,
]

CONTENT_TASK_FIELDS = [
    {"field_name": "标题", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "内容类型",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "options": ["行业洞察", "产品介绍", "用户故事", "数据分析"],
    },
    {"field_name": "状态", "type": SINGLE_SELECT_FIELD_TYPE, "options": _ALL_STATUSES},
    {"field_name": "编辑备注", "type": TEXT_FIELD_TYPE},
    {"field_name": "草稿内容", "type": TEXT_FIELD_TYPE},
    {"field_name": "审核意见", "type": TEXT_FIELD_TYPE},
    {"field_name": "发布时间", "type": TEXT_FIELD_TYPE},
    {"field_name": "质量评分", "type": NUMBER_FIELD_TYPE},
]

PERFORMANCE_FIELDS = [
    {"field_name": "员工姓名", "type": TEXT_FIELD_TYPE},
    {"field_name": "角色", "type": TEXT_FIELD_TYPE},
    {"field_name": "处理任务数", "type": NUMBER_FIELD_TYPE},
    {"field_name": "通过率", "type": NUMBER_FIELD_TYPE},
    {"field_name": "平均质量分", "type": NUMBER_FIELD_TYPE},
    {"field_name": "更新时间", "type": TEXT_FIELD_TYPE},
]

REPORT_FIELDS = [
    {"field_name": "报告周期", "type": TEXT_FIELD_TYPE},
    {"field_name": "总产出", "type": NUMBER_FIELD_TYPE},
    {"field_name": "通过率", "type": NUMBER_FIELD_TYPE},
    {"field_name": "摘要", "type": TEXT_FIELD_TYPE},
    {"field_name": "关键指标", "type": TEXT_FIELD_TYPE},
    {"field_name": "改进建议", "type": TEXT_FIELD_TYPE},
    {"field_name": "生成时间", "type": TEXT_FIELD_TYPE},
]

SEED_TASKS = [
    ("AI 大模型技术全景扫描", "行业洞察"),
    ("飞书多维表格核心功能解析", "产品介绍"),
    ("中小企业数字化转型案例研究", "用户故事"),
    ("2024年SaaS行业增长数据分析", "数据分析"),
]
