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
TABLE_DATASOURCE = "📚 数据源库"  # v8.6.16 — 独立数据源表（B 方案）
TABLE_EVIDENCE = "证据链"
TABLE_REVIEW = "产出评审"
TABLE_ACTION = "交付动作"
TABLE_REVIEW_HISTORY = "复核历史"
TABLE_DELIVERY_ARCHIVE = "交付结果归档"
TABLE_AUTOMATION_LOG = "自动化日志"
TABLE_TEMPLATE_CENTER = "模板配置中心"


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

OUTPUT_PURPOSE_OPTIONS = [
    {"name": "经营诊断", "color": 6},
    {"name": "管理决策", "color": 1},
    {"name": "执行跟进", "color": 4},
    {"name": "汇报展示", "color": 5},
    {"name": "补数核验", "color": 3},
]

BUSINESS_STAGE_OPTIONS = [
    {"name": "0-1探索", "color": 7},
    {"name": "增长爬坡", "color": 4},
    {"name": "稳定运营", "color": 6},
    {"name": "下滑修复", "color": 1},
]

REVIEW_RECOMMEND_OPTIONS = [
    {"name": "直接采用", "color": 4},
    {"name": "补数后复核", "color": 3},
    {"name": "建议重跑", "color": 1},
]

WORKFLOW_ROUTE_OPTIONS = [
    {"name": "直接汇报", "color": 4},
    {"name": "等待拍板", "color": 1},
    {"name": "直接执行", "color": 6},
    {"name": "补数复核", "color": 3},
    {"name": "重新分析", "color": 2},
]

RESPONSIBILITY_ROLE_OPTIONS = [
    {"name": "系统调度", "color": 0},
    {"name": "汇报对象", "color": 5},
    {"name": "拍板人", "color": 1},
    {"name": "执行人", "color": 6},
    {"name": "复核人", "color": 3},
    {"name": "复盘负责人", "color": 7},
    {"name": "已归档", "color": 4},
]

NATIVE_ACTION_OPTIONS = [
    {"name": "等待分析完成", "color": 0},
    {"name": "发送汇报", "color": 5},
    {"name": "管理拍板", "color": 1},
    {"name": "执行落地", "color": 6},
    {"name": "安排复核", "color": 3},
    {"name": "进入复盘", "color": 7},
    {"name": "归档沉淀", "color": 4},
]

EXCEPTION_STATUS_OPTIONS = [
    {"name": "正常", "color": 4},
    {"name": "需关注", "color": 3},
    {"name": "已异常", "color": 1},
]

EXCEPTION_TYPE_OPTIONS = [
    {"name": "无", "color": 0},
    {"name": "责任人待指派", "color": 3},
    {"name": "拍板滞留", "color": 1},
    {"name": "执行超期", "color": 1},
    {"name": "复核超时", "color": 2},
    {"name": "复盘滞留", "color": 7},
]

ACTION_TYPE_OPTIONS = [
    {"name": "发送汇报", "color": 5},
    {"name": "创建执行任务", "color": 4},
    {"name": "创建复核任务", "color": 3},
    {"name": "自动跟进任务", "color": 6},
    {"name": "工作流记录", "color": 0},
]

ACTION_STATUS_OPTIONS = [
    {"name": "待执行", "color": 3},
    {"name": "已完成", "color": 4},
    {"name": "已跳过", "color": 0},
    {"name": "执行失败", "color": 1},
]

ARCHIVE_STATUS_OPTIONS = [
    {"name": "待汇报", "color": 5},
    {"name": "待拍板", "color": 1},
    {"name": "待执行", "color": 6},
    {"name": "待复核", "color": 3},
    {"name": "已归档", "color": 0},
]


def priority_score(priority_value: str | None) -> int:
    """v8.6.20：把「优先级」选项名映射到「综合评分」数值（替代飞书公式不生效问题）。
    P0→100 / P1→75 / P2→50 / P3 或缺省→25。"""
    s = str(priority_value or "").upper()
    if "P0" in s or "紧急" in s:
        return 100
    if "P1" in s or "高" in s:
        return 75
    if "P2" in s or "中" in s:
        return 50
    return 25


def health_score(health_value: str | None) -> int:
    """v8.6.20：「健康度评级」→「健康度数值」。🟢→100 / 🟡→60 / 🔴→20 / ⚪/缺省→0。"""
    s = str(health_value or "")
    if "🟢" in s or "健康" in s:
        return 100
    if "🟡" in s or "关注" in s:
        return 60
    if "🔴" in s or "预警" in s:
        return 20
    return 0

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
    {"field_name": "目标对象", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "输出目的",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": OUTPUT_PURPOSE_OPTIONS,
    },
    {"field_name": "套用模板", "type": TEXT_FIELD_TYPE},
    {"field_name": "成功标准", "type": TEXT_FIELD_TYPE},
    {"field_name": "约束条件", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "业务阶段",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": BUSINESS_STAGE_OPTIONS,
    },
    {"field_name": "引用数据集", "type": TEXT_FIELD_TYPE},
    {"field_name": "依赖任务编号", "type": TEXT_FIELD_TYPE},  # 逗号分隔任务编号，如 "1,3"；只有这些任务全部已完成才会启动本任务
    {"field_name": "数据源", "type": TEXT_FIELD_TYPE},  # 用户粘贴 CSV / markdown / 纯文本作为分析输入
    {
        "field_name": "任务图像",
        "type": ATTACHMENT_FIELD_TYPE,
        "ui_type": "Attachment",
    },  # 仪表盘截图/手写白板/图表照 — vision LLM 转文字注入分析
    {
        "field_name": "最新评审动作",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": REVIEW_RECOMMEND_OPTIONS,
    },
    {"field_name": "最新评审摘要", "type": TEXT_FIELD_TYPE},
    {"field_name": "最新管理摘要", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "汇报就绪度",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
    },
    {
        "field_name": "证据条数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "高置信证据数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "硬证据数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "待验证证据数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "进入CEO汇总证据数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "决策事项数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "需补数条数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "工作流路由",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": WORKFLOW_ROUTE_OPTIONS,
    },
    {"field_name": "工作流消息包", "type": TEXT_FIELD_TYPE},
    {"field_name": "工作流执行包", "type": TEXT_FIELD_TYPE},
    {"field_name": "待发送汇报", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {"field_name": "待创建执行任务", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {"field_name": "待安排复核", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {
        "field_name": "建议复核时间",
        "type": DATE_FIELD_TYPE,
        "ui_type": "DateTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm", "auto_fill": False},
    },
    {"field_name": "汇报对象", "type": TEXT_FIELD_TYPE},
    {"field_name": "拍板负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "执行负责人", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "执行截止时间",
        "type": DATE_FIELD_TYPE,
        "ui_type": "DateTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm", "auto_fill": False},
    },
    {"field_name": "复核负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "复盘负责人", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "复核SLA小时",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "当前责任角色",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": RESPONSIBILITY_ROLE_OPTIONS,
    },
    {"field_name": "当前责任人", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "当前原生动作",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": NATIVE_ACTION_OPTIONS,
    },
    {
        "field_name": "异常状态",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": EXCEPTION_STATUS_OPTIONS,
    },
    {
        "field_name": "异常类型",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": EXCEPTION_TYPE_OPTIONS,
    },
    {"field_name": "异常说明", "type": TEXT_FIELD_TYPE},
    {"field_name": "汇报版本号", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "归档状态",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": ARCHIVE_STATUS_OPTIONS,
    },
    {"field_name": "是否已拍板", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {"field_name": "待拍板确认", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {"field_name": "拍板人", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "拍板时间",
        "type": DATE_FIELD_TYPE,
        "ui_type": "DateTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm", "auto_fill": False},
    },
    {"field_name": "是否已执行落地", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {"field_name": "待执行确认", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {
        "field_name": "执行完成时间",
        "type": DATE_FIELD_TYPE,
        "ui_type": "DateTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm", "auto_fill": False},
    },
    {"field_name": "是否进入复盘", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {"field_name": "待复盘确认", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
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
    {"field_name": "完成时间", "type": TEXT_FIELD_TYPE},  # v8.6.x 旧字段，保留兼容老 base
    # v8.6.19 新增 — 双字段过渡，DateTime 类型可被甘特视图识别为时间轴端点
    {
        "field_name": "完成日期",
        "type": DATE_FIELD_TYPE,
        "ui_type": "DateTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm", "auto_fill": False},
    },
    # v8.6.19 — 负责人字段（仅 UI 协作；scheduler 不写）
    {
        "field_name": "负责人",
        "type": PERSON_FIELD_TYPE,
        "ui_type": "User",
        "property": {"multiple": False},
    },
    # v8.6.20 — 综合评分（Number，scheduler 写）
    # v8.6.19 实测：飞书公式字段对 SingleSelect 字段的 .CONTAIN 不生效，
    # 公式 IF(.CONTAIN("P0"),100,...) 永远命中默认 25 分支（实测 8/8 任务都 25）。
    # 飞书公式语法对 OpenAPI 创建的公式字段在 SingleSelect 下不可靠，改用 Number
    # 字段 + scheduler/runner 主动写值，100% 可控。
    {
        "field_name": "综合评分",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
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
        # v8.6.20 — 健康度数值（Number，write_agent_outputs 写值）
        # 同综合评分的 v8.6.19 实测：公式 IF(.CONTAIN("健康"),100,...) 不生效，
        # 改 Number + 主动写。
        {
            "field_name": "健康度数值",
            "type": NUMBER_FIELD_TYPE,
            "ui_type": "Number",
            "property": {"formatter": "0"},
        },
        {"field_name": "证据摘要", "type": TEXT_FIELD_TYPE},
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
        {"field_name": "一句话结论", "type": TEXT_FIELD_TYPE},
        {"field_name": "核心结论", "type": TEXT_FIELD_TYPE},
        {"field_name": "重要机会", "type": TEXT_FIELD_TYPE},
        {"field_name": "重要风险", "type": TEXT_FIELD_TYPE},
        {"field_name": "CEO决策事项", "type": TEXT_FIELD_TYPE},
        {"field_name": "管理摘要", "type": TEXT_FIELD_TYPE},
        {"field_name": "首要动作", "type": TEXT_FIELD_TYPE},
        {"field_name": "汇报风险", "type": TEXT_FIELD_TYPE},
        {"field_name": "高管一页纸", "type": TEXT_FIELD_TYPE},
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
        {"field_name": "必须拍板事项", "type": TEXT_FIELD_TYPE},
        {"field_name": "可授权事项", "type": TEXT_FIELD_TYPE},
        {"field_name": "需补数事项", "type": TEXT_FIELD_TYPE},
        {"field_name": "立即执行事项", "type": TEXT_FIELD_TYPE},
        {
            "field_name": "证据充分度",
            "type": NUMBER_FIELD_TYPE,
            "ui_type": "Rating",
            "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
        },
        {
            "field_name": "生成时间",
            "type": CREATED_TIME_FIELD_TYPE,
            "ui_type": "CreatedTime",
            "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
        },
    ]


EVIDENCE_TYPE_OPTIONS = [
    {"name": "real_data", "color": 4},
    {"name": "benchmark", "color": 6},
    {"name": "upstream", "color": 5},
    {"name": "judgment", "color": 0},
]

EVIDENCE_USAGE_OPTIONS = [
    {"name": "insight", "color": 6},
    {"name": "opportunity", "color": 4},
    {"name": "risk", "color": 1},
    {"name": "decision", "color": 7},
]

EVIDENCE_CONFIDENCE_OPTIONS = [
    {"name": "high", "color": 4},
    {"name": "medium", "color": 3},
    {"name": "low", "color": 1},
]

EVIDENCE_GRADE_OPTIONS = [
    {"name": "硬证据", "color": 4},
    {"name": "推断", "color": 6},
    {"name": "待验证", "color": 3},
]

EVIDENCE_FIELDS = [
    {"field_name": "证据标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "岗位角色",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": AGENT_ROLE_OPTIONS,
    },
    {"field_name": "结论摘要", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "证据类型",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": EVIDENCE_TYPE_OPTIONS,
    },
    {
        "field_name": "证据用途",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": EVIDENCE_USAGE_OPTIONS,
    },
    {"field_name": "证据内容", "type": TEXT_FIELD_TYPE},
    {"field_name": "引用来源", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "证据置信度",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": EVIDENCE_CONFIDENCE_OPTIONS,
    },
    {
        "field_name": "证据等级",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": EVIDENCE_GRADE_OPTIONS,
    },
    {"field_name": "进入CEO汇总", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


REVIEW_FIELDS = [
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "评审结论", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "推荐动作",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": REVIEW_RECOMMEND_OPTIONS,
    },
    {
        "field_name": "真实性",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
    },
    {
        "field_name": "决策性",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
    },
    {
        "field_name": "可执行性",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
    },
    {
        "field_name": "闭环准备度",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
    },
    {"field_name": "需补数事项", "type": TEXT_FIELD_TYPE},
    {"field_name": "评审摘要", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


ACTION_FIELDS = [
    {"field_name": "动作标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "动作类型",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": ACTION_TYPE_OPTIONS,
    },
    {
        "field_name": "动作状态",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": ACTION_STATUS_OPTIONS,
    },
    {
        "field_name": "工作流路由",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": WORKFLOW_ROUTE_OPTIONS,
    },
    {"field_name": "动作内容", "type": TEXT_FIELD_TYPE},
    {"field_name": "执行结果", "type": TEXT_FIELD_TYPE},
    {"field_name": "关联记录ID", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


REVIEW_HISTORY_FIELDS = [
    {"field_name": "复核标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务编号", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "复核轮次",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {
        "field_name": "推荐动作",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": REVIEW_RECOMMEND_OPTIONS,
    },
    {
        "field_name": "工作流路由",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": WORKFLOW_ROUTE_OPTIONS,
    },
    {"field_name": "触发原因", "type": TEXT_FIELD_TYPE},
    {"field_name": "复核结论", "type": TEXT_FIELD_TYPE},
    {"field_name": "前次评审动作", "type": TEXT_FIELD_TYPE},
    {"field_name": "新旧结论差异", "type": TEXT_FIELD_TYPE},
    {"field_name": "需补数事项", "type": TEXT_FIELD_TYPE},
    {"field_name": "关联记录ID", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


DELIVERY_ARCHIVE_FIELDS = [
    {"field_name": "归档标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务编号", "type": TEXT_FIELD_TYPE},
    {"field_name": "汇报版本号", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "工作流路由",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": WORKFLOW_ROUTE_OPTIONS,
    },
    {
        "field_name": "归档状态",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": ARCHIVE_STATUS_OPTIONS,
    },
    {
        "field_name": "最新评审动作",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": REVIEW_RECOMMEND_OPTIONS,
    },
    {"field_name": "一句话结论", "type": TEXT_FIELD_TYPE},
    {"field_name": "管理摘要", "type": TEXT_FIELD_TYPE},
    {"field_name": "首要动作", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "汇报就绪度",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Rating",
        "property": {"formatter": "0", "min": 0, "max": 5, "rating": {"symbol": "star"}},
    },
    {"field_name": "工作流消息包", "type": TEXT_FIELD_TYPE},
    {"field_name": "汇报对象", "type": TEXT_FIELD_TYPE},
    {"field_name": "执行负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "复核负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "关联记录ID", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


AUTOMATION_LOG_FIELDS = [
    {"field_name": "日志标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "任务标题", "type": TEXT_FIELD_TYPE},
    {"field_name": "节点名称", "type": TEXT_FIELD_TYPE},
    {"field_name": "触发来源", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "执行状态",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": ACTION_STATUS_OPTIONS,
    },
    {
        "field_name": "工作流路由",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": WORKFLOW_ROUTE_OPTIONS,
    },
    {"field_name": "日志摘要", "type": TEXT_FIELD_TYPE},
    {"field_name": "详细结果", "type": TEXT_FIELD_TYPE},
    {"field_name": "关联记录ID", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


TEMPLATE_CENTER_FIELDS = [
    {"field_name": "模板名称", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "适用工作流路由",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": WORKFLOW_ROUTE_OPTIONS,
    },
    {
        "field_name": "适用输出目的",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": OUTPUT_PURPOSE_OPTIONS,
    },
    {"field_name": "汇报模板", "type": TEXT_FIELD_TYPE},
    {"field_name": "执行模板", "type": TEXT_FIELD_TYPE},
    {"field_name": "默认汇报对象", "type": TEXT_FIELD_TYPE},
    {"field_name": "默认拍板负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "默认执行负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "默认复核负责人", "type": TEXT_FIELD_TYPE},
    {"field_name": "默认复盘负责人", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "默认复核SLA小时",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {"field_name": "模板说明", "type": TEXT_FIELD_TYPE},
    {"field_name": "启用", "type": CHECKBOX_FIELD_TYPE, "ui_type": "Checkbox"},
    {
        "field_name": "生成时间",
        "type": CREATED_TIME_FIELD_TYPE,
        "ui_type": "CreatedTime",
        "property": {"date_formatter": "yyyy-MM-dd HH:mm"},
    },
]


DATASOURCE_TYPE_OPTIONS = [
    {"name": "时间序列指标", "color": 6},
    {"name": "渠道转化", "color": 8},
    {"name": "关键词机会", "color": 4},
    {"name": "功能 RICE", "color": 7},
    {"name": "用户漏斗", "color": 2},
    {"name": "财务报表", "color": 3},
    {"name": "竞品对标", "color": 5},
    {"name": "其他", "color": 0},
]


# v8.6.16 — 独立数据源表（B 方案）：数据源跟分析任务解耦，便于复用、版本管理、UI 浏览
DATASOURCE_FIELDS = [
    {"field_name": "数据集名称", "type": TEXT_FIELD_TYPE},  # 主字段
    {
        "field_name": "类型",
        "type": SINGLE_SELECT_FIELD_TYPE,
        "ui_type": "SingleSelect",
        "options": DATASOURCE_TYPE_OPTIONS,
    },
    {"field_name": "字段说明", "type": TEXT_FIELD_TYPE},  # 数据列定义说明
    {"field_name": "数据来源", "type": TEXT_FIELD_TYPE},
    {"field_name": "可信等级", "type": TEXT_FIELD_TYPE},
    {"field_name": "适用任务类型", "type": TEXT_FIELD_TYPE},
    {"field_name": "原始 CSV", "type": TEXT_FIELD_TYPE},  # 纯 CSV，给 agent 解析
    {"field_name": "渲染表格", "type": TEXT_FIELD_TYPE},  # markdown table，飞书 UI 友好渲染
    {
        "field_name": "数据行数",
        "type": NUMBER_FIELD_TYPE,
        "ui_type": "Number",
        "property": {"formatter": "0"},
    },
    {"field_name": "原始数据文件", "type": ATTACHMENT_FIELD_TYPE, "ui_type": "Attachment"},
    {"field_name": "最近校验说明", "type": TEXT_FIELD_TYPE},
    {
        "field_name": "创建时间",
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
# v8.6.9：从 demo_data.py 导入 InsightHub 完整虚构产品场景的 7 条任务种子
# （从 4 条扩展到 7 条，覆盖数据复盘/运营诊断/增长优化/产品规划/综合分析全部维度，
# 共享同一个虚拟产品背景，让 7 个 agent 输出能横向对比关联）。
#
# ⚠️ 所有数字都是手编演示数据，不是真实业务数据 — 竞赛交付前必须替换。
from app.bitable_workflow.demo_data import SEED_TASKS  # noqa: F401  (re-export)
