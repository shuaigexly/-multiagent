"""内容运营虚拟组织 — 多维表格结构常量（七岗多智能体 · 高级视觉版）

升级要点：
  - 单选字段带颜色语义（状态/评级/维度）
  - 评分字段使用星星（置信度/紧急度/活跃度）
  - 进度条字段可视化百分比（任务进度）
  - 自动时间字段（创建/最近更新）取代手动时间戳
  - 自动编号字段提供任务唯一 ID
"""

# 基础类型
TEXT_FIELD_TYPE = 1
NUMBER_FIELD_TYPE = 2
SINGLE_SELECT_FIELD_TYPE = 3
MULTI_SELECT_FIELD_TYPE = 4
DATE_FIELD_TYPE = 5
CHECKBOX_FIELD_TYPE = 7
PERSON_FIELD_TYPE = 11
URL_FIELD_TYPE = 15
ATTACHMENT_FIELD_TYPE = 17
LINKED_RECORD_FIELD_TYPE = 18
FORMULA_FIELD_TYPE = 20
CREATED_TIME_FIELD_TYPE = 1001
MODIFIED_TIME_FIELD_TYPE = 1002
AUTO_NUMBER_FIELD_TYPE = 1005

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

# 颜色编码（飞书 0-54），参考飞书标签色板：
#   0 灰  1 红  2 橙  3 黄  4 绿  5 青  6 蓝  7 紫  8 粉
STATUS_OPTIONS = [
    {"name": Status.PENDING, "color": 0},      # 灰：待分析
    {"name": Status.ANALYZING, "color": 3},    # 黄：分析中
    {"name": Status.COMPLETED, "color": 4},    # 绿：已完成
    {"name": Status.ARCHIVED, "color": 6},     # 蓝：已归档
]

ANALYSIS_DIMENSIONS = ["内容战略", "数据复盘", "增长优化", "产品规划", "运营诊断", "综合分析"]
DIMENSION_OPTIONS = [
    {"name": "内容战略", "color": 8},  # 粉
    {"name": "数据复盘", "color": 6},  # 蓝
    {"name": "增长优化", "color": 4},  # 绿
    {"name": "产品规划", "color": 7},  # 紫
    {"name": "运营诊断", "color": 2},  # 橙
    {"name": "综合分析", "color": 5},  # 青
]

PRIORITY_OPTIONS = [
    {"name": "P0 紧急", "color": 1},   # 红
    {"name": "P1 高", "color": 2},     # 橙
    {"name": "P2 中", "color": 3},     # 黄
    {"name": "P3 低", "color": 0},     # 灰
]

HEALTH_OPTIONS = [
    {"name": "🟢 健康", "color": 4},
    {"name": "🟡 关注", "color": 3},
    {"name": "🔴 预警", "color": 1},
    {"name": "⚪ 数据不足", "color": 0},
]

AGENT_ROLE_OPTIONS = [
    {"name": "📊 数据分析师", "color": 6},
    {"name": "📝 内容负责人", "color": 8},
    {"name": "🔍 SEO/增长顾问", "color": 4},
    {"name": "📱 产品经理", "color": 7},
    {"name": "⚙️ 运营负责人", "color": 2},
    {"name": "💰 财务顾问", "color": 3},
    {"name": "👔 CEO 助理", "color": 5},
]

# 分析任务表字段（主控表）
TASK_FIELDS = [
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},  # 主字段
    {
        "field_name": "任务编号",
        "type": AUTO_NUMBER_FIELD_TYPE,
        "ui_type": "AutoNumber",
        "property": {"auto_serial": {"type": "auto_increment_number"}},
    },
    {
        "field_name": "分析维度",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": DIMENSION_OPTIONS,
    },
    {
        "field_name": "优先级",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": PRIORITY_OPTIONS,
    },
    {
        "field_name": "状态",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": STATUS_OPTIONS,
    },
    {"field_name": "当前阶段", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "进度",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Progress",
        "property": {"formatter": "0%", "min": 0, "max": 1, "range_customize": True},
    },
    {"field_name": "背景说明", "type": TEXT_FIELD_TYPE},
    {"field_name": "依赖任务编号", "type": TEXT_FIELD_TYPE},  # 逗号分隔任务编号，如 "1,3"；只有这些任务全部已完成才会启动本任务
    {"field_name": "数据源", "type": TEXT_FIELD_TYPE},  # 用户粘贴 CSV / markdown / 纯文本作为分析输入
    {
        "field_name": "任务图像",
        "type": ATTACHMENT_FIELD_TYPE,
        "ui_type": "Attachment",
    },  # 仪表盘截图/手写白板/图表照 — vision LLM 转文字注入分析
    {
        "field_name": "创建时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
    {
        "field_name": "最近更新",
        "type": MODIFIED_TIME_FIELD_TYPE,
        "ui_type": "ModifiedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
    {"field_name": "完成时间", "type": TEXT_FIELD_TYPE},
]


def agent_output_fields(task_table_id: str) -> list[dict]:
    """岗位分析表字段：每个 agent 一条。

    v8.6.1: 删除「关联任务」LinkedRecord 字段 — 飞书 records POST/PUT/batch
    三个写接口实测全部不接受 LinkedRecord 字段写入（code=1254067），属于
    Feishu Bitable 平台硬限制。改用「任务标题」文本字段做逻辑关联。
    task_table_id 参数保留以兼容 setup_workflow 调用签名。
    """
    _ = task_table_id  # 未使用，保留兼容
    return [
        {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},  # 主字段，逻辑关联
        {
            "field_name": "岗位角色",
            "type": SINGLE_SELECT_FIELD_TYPE,
            "ui_type": "SingleSelect",
            "options": AGENT_ROLE_OPTIONS,
        },
        {
            "field_name": "健康度评级",
            "type": SINGLE_SELECT_FIELD_TYPE,
            "ui_type": "SingleSelect",
            "options": HEALTH_OPTIONS,
        },
        {"field_name": "分析摘要", "type": TEXT_FIELD_TYPE},
        {"field_name": "行动项", "type": TEXT_FIELD_TYPE},
        {
            "field_name": "行动项数",
            "type": NUMBER_FIELD_TYPE,
            "ui_type": "Number",
            "property": {"formatter": "0"},
        },
        {
            "field_name": "置信度",
            "type": NUMBER_FIELD_TYPE,
            "ui_type": "Rating",
            "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
        },
        {"field_name": "分析思路", "type": TEXT_FIELD_TYPE},
        {"field_name": "图表数据", "type": TEXT_FIELD_TYPE},
        {"field_name": "图表", "type": ATTACHMENT_FIELD_TYPE, "ui_type": "Attachment"},
        {
            "field_name": "生成时间",
            "type": CREATED_TIME_FIELD_TYPE,
            "ui_type": "CreatedTime",
            "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
        },
    ]


def report_fields(task_table_id: str) -> list[dict]:
    """综合报告表字段：CEO 助理的最终决策汇总。

    v8.6.1: 同 agent_output_fields，删除 LinkedRecord 字段（飞书 API 平台限制）。
    """
    _ = task_table_id  # 未使用，保留兼容
    return [
        {"field_name": "报告标题", "type": TEXT_FIELD_TYPE},  # 主字段，逻辑关联
        {
            "field_name": "综合健康度",
            "type": SINGLE_SELECT_FIELD_TYPE,
            "ui_type": "SingleSelect",
            "options": HEALTH_OPTIONS,
        },
        {"field_name": "核心结论", "type": TEXT_FIELD_TYPE},
        {"field_name": "重要机会", "type": TEXT_FIELD_TYPE},
        {"field_name": "重要风险", "type": TEXT_FIELD_TYPE},
        {"field_name": "CEO决策事项", "type": TEXT_FIELD_TYPE},
        {"field_name": "管理摘要", "type": TEXT_FIELD_TYPE},
        {
            "field_name": "参与岗位数",
            "type": NUMBER_FIELD_TYPE,
            "ui_type": "Number",
            "property": {"formatter": "0"},
        },
        {
            "field_name": "决策紧急度",
            "type": NUMBER_FIELD_TYPE,
            "ui_type": "Rating",
            "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "fire"}},
        },
        {
            "field_name": "生成时间",
            "type": CREATED_TIME_FIELD_TYPE,
            "ui_type": "CreatedTime",
            "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
        },
    ]


PERFORMANCE_FIELDS = [
    {"field_name": "员工姓名", "type": TEXT_FIELD_TYPE},  # 主字段
    {
        "field_name": "岗位",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": AGENT_ROLE_OPTIONS,
    },
    {"field_name": "角色", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "处理任务数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "活跃度",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "thumbsup"}},
    },
    {
        "field_name": "最近更新",
        "type": MODIFIED_TIME_FIELD_TYPE,
        "ui_type": "ModifiedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]

# 初始种子任务: (标题, 分析维度, 背景说明, 数据源)
# v8.6.5：之前 SEED 不带「数据源」，导致 6 个 agent 全部基于背景说明跑通用分析，
# 看起来"内容干巴巴"。现在每个种子任务都附带一段最小可用的真实数据（CSV/JSON/markdown），
# LLM 才能真正算出指标变化，输出图表才有数字。
SEED_TASKS = [
    (
        "AI 产品内容战略分析",
        "内容战略",
        "分析当前 AI 工具类产品的内容运营策略，识别差异化机会，规划内容资产布局",
        # 季度核心指标 CSV，覆盖增长/留存/付费/获客四个维度
        "指标,一月,二月,三月\n"
        "MAU,85000,98000,112000\n"
        "DAU,32000,38000,45000\n"
        "30日留存%,32,35,38\n"
        "付费转化%,3.2,3.8,4.5\n"
        "LTV,180,195,212\n"
        "CAC,72,68,65\n"
        "内容产出量,180,240,320\n"
        "人均时长(分),18,21,23",
    ),
    (
        "内容运营核心指标复盘",
        "数据复盘",
        "复盘近期内容产出、分发、转化各环节关键指标，识别瓶颈并提出改进方向",
        "渠道,曝光,点击,CTR%,转化,转化率%\n"
        "微信公众号,420000,12600,3.0,378,3.0\n"
        "知乎,180000,8100,4.5,243,3.0\n"
        "小红书,260000,15600,6.0,468,3.0\n"
        "搜索引擎,95000,2850,3.0,114,4.0\n"
        "私域社群,38000,3420,9.0,205,6.0",
    ),
    (
        "SEO 增长机会全景扫描",
        "增长优化",
        "分析行业关键词机会、内容缺口，规划 SEO 驱动的自然流量增长路径",
        "关键词,月搜索量,竞争度,当前排名,意图\n"
        "AI 工具推荐,18000,中,28,商业\n"
        "ChatGPT 替代,12000,低,9,信息\n"
        "AI 写作工具,9500,高,42,商业\n"
        "AI 绘画教程,7800,低,15,信息\n"
        "AI 提示词大全,15000,低,35,信息\n"
        "免费 AI 工具,22000,高,55,商业",
    ),
    (
        "内容产品功能路线图规划",
        "产品规划",
        "梳理内容创作与分发产品功能需求，制定优先级与 MVP 计划，对齐业务目标",
        "功能,RICE-Reach,RICE-Impact,RICE-Confidence,RICE-Effort,RICE 总分\n"
        "智能搜索算法升级,8000,3,0.9,5,4320\n"
        "个性化推荐引擎,12000,3,0.8,8,3600\n"
        "内容质量评分系统,5000,2,0.9,3,3000\n"
        "创作者协作工作台,3000,2,0.7,5,840\n"
        "AI 写作辅助助手,7000,3,0.6,8,1575",
    ),
]
