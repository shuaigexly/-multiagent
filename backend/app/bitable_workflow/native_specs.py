"""Shared Feishu-native scaffold specs for forms, automations, workflows, dashboards, and roles."""

from __future__ import annotations

import time
from typing import Any

from app.bitable_workflow import schema as workflow_schema


def build_form_spec() -> dict[str, Any]:
    questions = [
        {"type": "text", "title": "任务标题", "required": True, "description": "用于主表任务标题，建议用一句话准确描述问题。"},
        {"type": "text", "title": "背景说明", "required": True, "description": "补充当前问题背景、上下文和已知限制。"},
        {
            "type": "select",
            "title": "输出目的",
            "required": True,
            "multiple": False,
            "options": [
                {"name": "经营诊断", "hue": "Blue"},
                {"name": "管理决策", "hue": "Red"},
                {"name": "执行跟进", "hue": "Green"},
                {"name": "汇报展示", "hue": "Blue"},
                {"name": "补数核验", "hue": "Yellow"},
            ],
        },
        {
            "type": "select",
            "title": "优先级",
            "required": True,
            "multiple": False,
            "options": [
                {"name": "P0 紧急", "hue": "Red"},
                {"name": "P1 高", "hue": "Orange"},
                {"name": "P2 中", "hue": "Yellow"},
                {"name": "P3 低", "hue": "Gray"},
            ],
        },
        {"type": "text", "title": "目标对象", "required": False, "description": "说明这份产出面向谁，例如 CEO / 管理层 / 业务负责人。"},
        {
            "type": "select",
            "title": "汇报对象级别",
            "required": False,
            "multiple": False,
            "options": [
                {"name": "负责人", "hue": "Green"},
                {"name": "部门管理层", "hue": "Blue"},
                {"name": "CEO / CXO", "hue": "Red"},
            ],
        },
        {"type": "text", "title": "成功标准", "required": False, "description": "定义什么样的结果算交付完成。"},
        {"type": "text", "title": "引用数据集", "required": False, "description": "填数据集名称、表名或已有链接。"},
        {"type": "attachment", "title": "任务图像", "required": False, "description": "可上传截图、图表、白板拍照等。"},
    ]
    return {
        "name": "任务收集表单",
        "description": "用于把业务问题直接投递到 `分析任务` 主表。提交后，系统会按输出目的、优先级和角色契约继续流转。",
        "questions": questions,
        "sections": [
            {"title": "任务基础信息", "question_titles": ["任务标题", "背景说明", "输出目的", "优先级"]},
            {"title": "交付上下文", "question_titles": ["目标对象", "汇报对象级别", "成功标准", "引用数据集", "任务图像"]},
        ],
    }


def build_automation_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "A1 新任务入场提醒",
            "summary": "新任务进入主表后，立即回写原生责任状态，并写入一条自动化日志。",
            "trigger": "新增记录时",
            "condition": "任务标题非空",
            "action": "发送飞书消息 + 回写自动化状态 + 记录自动化日志",
            "primary_field": "任务来源",
            "native_goal": "把业务提交入口和原生任务接收闭环连接起来。",
            "receiver_binding_fields": [],
            "owner_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "requires_member_binding": False,
            "body": {
                "client_token": _token("a1"),
                "title": "A1 新任务入场提醒",
                "steps": [
                    _add_record_trigger("step_trigger", "分析任务", "任务标题", "新任务写入主表"),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生自动化已接收任务"),
                            _role_field("当前责任角色", "系统调度"),
                            _native_action_field("当前原生动作", "等待分析完成"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送新任务提醒",
                        "新任务已进入飞书原生交付闭环",
                        [
                            "主表已收到新的分析任务。",
                            "后续由调度器和飞书原生对象继续承接。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "A1 新任务入场提醒"),
                            _text_field("任务标题", "请在关联记录中查看原始任务"),
                            _text_field("节点名称", "A1 新任务入场提醒"),
                            _text_field("触发来源", "automation.intake"),
                            _action_status_field("执行状态", "已完成"),
                            _text_field("日志摘要", "已将新任务纳入飞书原生交付闭环"),
                            _text_field("详细结果", "请在主表继续查看任务状态、责任角色和后续原生动作。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A2 直接汇报自动提醒",
            "summary": "直接汇报任务满足汇报条件时，自动切换到汇报责任面，并创建一条汇报动作。",
            "trigger": "字段修改时",
            "condition": "待发送汇报 = 是 且 工作流路由 = 直接汇报",
            "action": "回写汇报责任角色 + 发送管理提醒 + 创建汇报动作",
            "primary_field": "工作流消息包",
            "native_goal": "把分析完成到管理汇报这一段尽量原生化。",
            "receiver_binding_fields": ["汇报对象OpenID"],
            "owner_binding_fields": ["汇报对象OpenID", "拍板负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a2"),
                "title": "A2 直接汇报自动提醒",
                "steps": [
                    _checkbox_trigger(
                        "step_trigger",
                        "待发送汇报",
                        "等待触发直接汇报动作",
                        extra_watch_info=[_option_condition("工作流路由", "直接汇报")],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生汇报发送中"),
                            _role_field("当前责任角色", "汇报对象"),
                            _native_action_field("当前原生动作", "发送汇报"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送汇报提醒",
                        "分析任务已进入管理汇报阶段",
                        [
                            "请在主表查看工作流消息包、管理摘要和汇报对象。",
                            "这条自动化已经把任务从分析阶段切换到汇报阶段。",
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建汇报动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "发送汇报"),
                            _action_status_field("动作状态", "待执行"),
                            _route_field("工作流路由", "直接汇报"),
                            _text_field("动作内容", "按主表中的工作流消息包发送汇报，并回填管理确认结果。"),
                            _text_field("执行结果", "自动化 scaffold 已创建动作，请在飞书补齐接收人和消息卡片。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A2b 待拍板汇报提醒",
            "summary": "待拍板任务满足汇报条件时，自动切换到汇报责任面，并创建一条待拍板汇报动作。",
            "trigger": "字段修改时",
            "condition": "待发送汇报 = 是 且 工作流路由 = 等待拍板",
            "action": "回写汇报责任角色 + 发送管理提醒 + 创建待拍板汇报动作",
            "primary_field": "工作流消息包",
            "native_goal": "把拍板前汇报动作沉淀到多维表格原生动作表，避免错分支。",
            "receiver_binding_fields": ["汇报对象OpenID", "拍板负责人OpenID"],
            "owner_binding_fields": ["汇报对象OpenID", "拍板负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a2b"),
                "title": "A2b 待拍板汇报提醒",
                "steps": [
                    _checkbox_trigger(
                        "step_trigger",
                        "待发送汇报",
                        "等待触发待拍板汇报动作",
                        extra_watch_info=[_option_condition("工作流路由", "等待拍板")],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生拍板汇报发送中"),
                            _role_field("当前责任角色", "汇报对象"),
                            _native_action_field("当前原生动作", "发送汇报"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送待拍板汇报提醒",
                        "分析任务已进入拍板前汇报阶段",
                        [
                            "请在主表查看工作流消息包、管理摘要、汇报对象和拍板负责人。",
                            "这条自动化已经把任务切换到待拍板汇报阶段。",
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建待拍板汇报动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "发送汇报"),
                            _action_status_field("动作状态", "待执行"),
                            _route_field("工作流路由", "等待拍板"),
                            _text_field("动作内容", "按主表中的工作流消息包发送汇报，并回填拍板确认结果。"),
                            _text_field("执行结果", "自动化 scaffold 已创建待拍板汇报动作，请在飞书补齐接收人、消息卡片和拍板反馈。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A3 执行任务自动创建",
            "summary": "执行分支触发后，自动写出执行动作，并把责任面切到执行人。",
            "trigger": "字段修改时",
            "condition": "待创建执行任务 = 是",
            "action": "回写执行责任角色 + 创建执行动作 + 提醒执行负责人",
            "primary_field": "工作流执行包",
            "native_goal": "把多 Agent 产出进一步推进到执行任务层。",
            "receiver_binding_fields": ["执行负责人OpenID"],
            "owner_binding_fields": ["执行负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a3"),
                "title": "A3 执行任务自动创建",
                "steps": [
                    _checkbox_trigger("step_trigger", "待创建执行任务", "等待触发执行动作"),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生执行动作创建中"),
                            _role_field("当前责任角色", "执行人"),
                            _native_action_field("当前原生动作", "执行落地"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建执行任务"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "创建执行任务"),
                            _action_status_field("动作状态", "待执行"),
                            _route_field("工作流路由", "直接执行"),
                            _text_field("动作内容", "按主表中的工作流执行包拆成可落地动作，并回填执行完成时间。"),
                            _text_field("执行结果", "自动化 scaffold 已创建执行动作，请在飞书任务中心补齐负责人和截止时间。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送执行提醒",
                        "分析任务已进入执行分支",
                        [
                            "执行动作已经写入交付动作表。",
                            "请在主表查看执行负责人、执行截止时间和执行包。",
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A4 复核提醒",
            "summary": "复核时间到达后，自动切换到复核责任面，并生成复核动作。",
            "trigger": "到达记录中的时间时",
            "condition": "待安排复核 = 是 且 建议复核时间到达",
            "action": "回写复核责任角色 + 创建复核动作 + 提醒复核负责人",
            "primary_field": "建议复核时间",
            "native_goal": "让补数、复核、重跑都围绕多维表格原生时点驱动。",
            "receiver_binding_fields": ["复核负责人OpenID"],
            "owner_binding_fields": ["复核负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a4"),
                "title": "A4 复核提醒",
                "steps": [
                    _reminder_trigger(
                        "step_trigger",
                        "建议复核时间",
                        "建议复核时间到达",
                        condition_list=[_bool_condition("待安排复核", True)],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生复核提醒已触发"),
                            _role_field("当前责任角色", "复核人"),
                            _native_action_field("当前原生动作", "安排复核"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建复核动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "创建复核任务"),
                            _action_status_field("动作状态", "待执行"),
                            _text_field("动作内容", "请按主表里的需补数条数、异常说明、当前路由和复核 SLA 继续处理。"),
                            _text_field("执行结果", "自动化 scaffold 已创建复核动作，请在飞书里绑定具体负责人、路由分支和复核清单。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送复核提醒",
                        "分析任务已到复核时间",
                        [
                            "复核动作已经写入交付动作表。",
                            "请按证据链、评审记录和复核历史继续补数或重跑。",
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A5 异常升级提醒",
            "summary": "异常任务进入人工接管路径，并把异常升级结果同步沉淀到日志表。",
            "trigger": "字段修改时",
            "condition": "异常状态 = 已异常",
            "action": "发送升级提醒 + 回写异常责任状态 + 记录异常日志",
            "primary_field": "异常类型",
            "native_goal": "把异常升级和人工接管固定在多维表格原生异常面。",
            "receiver_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "owner_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a5"),
                "title": "A5 异常升级提醒",
                "steps": [
                    _select_trigger("step_trigger", "异常状态", "已异常", "异常升级触发"),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "异常升级处理中"),
                            _native_action_field("当前原生动作", "进入复盘"),
                            _automation_status_field("自动化执行状态", "失败"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送异常升级提醒",
                        "分析任务出现异常，需要人工接管",
                        [
                            "请优先查看主表里的异常类型、异常说明和当前责任角色。",
                            "这条自动化只负责把异常暴露出来，具体处理动作仍建议在飞书里细化。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "A5 异常升级提醒"),
                            _text_field("任务标题", "请在主表查看对应异常任务"),
                            _text_field("节点名称", "A5 异常升级提醒"),
                            _text_field("触发来源", "automation.exception"),
                            _action_status_field("执行状态", "执行失败"),
                            _text_field("日志摘要", "任务已被标记为异常，并进入人工接管路径。"),
                            _text_field("详细结果", "请在主表继续补数、重跑或进入复盘闭环。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A6 超时未复核提醒",
            "summary": "复核时间已超且任务仍待安排复核时，自动催办复核负责人并写催办日志。",
            "trigger": "到达记录中的时间时",
            "condition": "待安排复核 = 是 且 建议复核时间超时",
            "action": "发送复核催办 + 保持复核责任面 + 记录超时日志",
            "primary_field": "建议复核时间",
            "native_goal": "把复核超时变成原生可见的催办节点，而不是只停在主表字段。",
            "receiver_binding_fields": ["复核负责人OpenID"],
            "owner_binding_fields": ["复核负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a6"),
                "title": "A6 超时未复核提醒",
                "steps": [
                    _reminder_trigger(
                        "step_trigger",
                        "建议复核时间",
                        "复核时间超时后催办",
                        condition_list=[_bool_condition("待安排复核", True)],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生复核超时催办中"),
                            _role_field("当前责任角色", "复核人"),
                            _native_action_field("当前原生动作", "安排复核"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送复核超时提醒",
                        "分析任务复核已超时",
                        [
                            "请优先检查建议复核时间、需补数事项和异常说明。",
                            "若已经完成复核，请回写主表并关闭待安排复核状态。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "A6 超时未复核提醒"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _text_field("节点名称", "A6 超时未复核提醒"),
                            _text_field("触发来源", "automation.review_overdue"),
                            _action_status_field("执行状态", "已完成"),
                            _text_field("日志摘要", "任务仍处于待安排复核，系统已触发原生催办。"),
                            _text_field("详细结果", "请在主表继续回写复核动作、补数进度和重跑结论。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A7 失败动作报警",
            "summary": "交付动作进入执行失败后，立即生成失败报警日志并提醒人工接管。",
            "trigger": "字段修改时",
            "condition": "交付动作.动作状态 = 执行失败",
            "action": "发送失败报警 + 记录失败日志",
            "primary_field": "动作状态",
            "native_goal": "把动作层失败从局部记录升级成可审计的原生告警面。",
            "receiver_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "owner_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a7"),
                "title": "A7 失败动作报警",
                "steps": [
                    _select_trigger(
                        "step_trigger",
                        "动作状态",
                        "执行失败",
                        "失败动作进入人工接管",
                        table_name="交付动作",
                    ),
                    _message_action(
                        "step_notify",
                        "发送失败动作报警",
                        "交付动作执行失败，需要人工接管",
                        [
                            "请查看失败动作的执行结果、动作内容和关联记录。",
                            "建议把失败原因、是否可重试、接管责任人同步回主表和日志表。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "A7 失败动作报警"),
                            _text_field("任务标题", "请在失败动作关联任务中查看"),
                            _text_field("节点名称", "A7 失败动作报警"),
                            _text_field("触发来源", "automation.action_failed"),
                            _action_status_field("执行状态", "执行失败"),
                            _text_field("日志摘要", "交付动作已进入执行失败，系统已触发失败告警。"),
                            _text_field("详细结果", "请在交付动作表查看失败详情，并在主表推进人工接管或重试。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "A8 归档提醒",
            "summary": "任务执行落地后，自动切换到复盘归档责任面，并生成归档提醒。",
            "trigger": "字段修改时",
            "condition": "状态 = 已完成 且 是否已执行落地 = 是",
            "action": "切换复盘责任面 + 发送归档提醒 + 写归档跟进动作",
            "primary_field": "是否已执行落地",
            "native_goal": "把执行完成后的最后一段闭环推进到飞书原生复盘归档面。",
            "receiver_binding_fields": ["复盘负责人OpenID"],
            "owner_binding_fields": ["复盘负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("a8"),
                "title": "A8 归档提醒",
                "steps": [
                    _checkbox_trigger(
                        "step_trigger",
                        "是否已执行落地",
                        "执行完成后进入归档提醒",
                        extra_watch_info=[_option_condition("状态", "已完成")],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生归档提醒已触发"),
                            _role_field("当前责任角色", "复盘负责人"),
                            _native_action_field("当前原生动作", "进入复盘"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建归档跟进动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "自动跟进任务"),
                            _action_status_field("动作状态", "待执行"),
                            _text_field("动作内容", "请补齐归档摘要、复盘结论、汇报版本号和交付结果归档记录。"),
                            _text_field("执行结果", "自动化 scaffold 已创建归档跟进动作，请在飞书里补齐复盘负责人和最终归档材料。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送归档提醒",
                        "分析任务已进入复盘归档阶段",
                        [
                            "请在主表与归档表补齐版本号、复盘结论和最终沉淀材料。",
                            "归档完成后应回写状态、归档状态和复盘确认字段。",
                        ],
                    ),
                ],
            },
        },
    ]


def build_workflow_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "W1 路由总分发工作流",
            "summary": "任务完成后把主表切换到原生交付阶段，并把路由信息沉淀到自动化日志。",
            "entry_condition": "状态 = 已完成",
            "route_field": "工作流路由",
            "actions": ["切换交付阶段", "广播交付提醒", "记录路由日志"],
            "native_goal": "让调度结果真正流向飞书原生交付面。",
            "receiver_binding_fields": ["汇报对象OpenID", "拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w1"),
                "title": "W1 路由总分发工作流",
                "steps": [
                    _select_trigger("step_trigger", "状态", "已完成", "完成任务进入原生交付"),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生交付路由已接管"),
                            _native_action_field("当前原生动作", "发送汇报"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送路由提醒",
                        "分析任务已完成，进入飞书原生交付阶段",
                        [
                            "请根据主表中的工作流路由、责任角色和异常状态继续处理。",
                            "该工作流的目标是把多 Agent 结果转成飞书原生操作面。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "W1 路由总分发工作流"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _text_field("节点名称", "W1 路由总分发工作流"),
                            _text_field("触发来源", "workflow.route.dispatch"),
                            _action_status_field("执行状态", "已完成"),
                            _text_field("日志摘要", "任务已从分析阶段切换到飞书原生交付阶段。"),
                            _text_field("详细结果", "后续请在主表查看待拍板确认、待执行确认、待安排复核等原生队列字段。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W2 汇报分支工作流",
            "summary": "直接汇报队列出现后，把任务切到汇报责任面，并沉淀管理汇报动作。",
            "entry_condition": "待发送汇报 = 是 且 工作流路由 = 直接汇报",
            "route_field": "工作流路由",
            "actions": ["切换汇报责任面", "发送管理提醒", "写入汇报动作"],
            "native_goal": "把直接汇报这条分支推进到飞书原生工作流，而不是只靠 API 回写。",
            "receiver_binding_fields": ["汇报对象OpenID", "拍板负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w2"),
                "title": "W2 汇报分支工作流",
                "steps": [
                    _checkbox_trigger(
                        "step_trigger",
                        "待发送汇报",
                        "进入直接汇报队列",
                        extra_watch_info=[_option_condition("工作流路由", "直接汇报")],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "原生汇报分支处理中"),
                            _role_field("当前责任角色", "汇报对象"),
                            _native_action_field("当前原生动作", "发送汇报"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送汇报提醒",
                        "分析任务已进入直接汇报分支",
                        [
                            "请重点查看工作流消息包、管理摘要和汇报对象。",
                            "汇报完成后，可继续回写管理反馈和归档状态。",
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建直接汇报动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "发送汇报"),
                            _action_status_field("动作状态", "待执行"),
                            _route_field("工作流路由", "直接汇报"),
                            _text_field("动作内容", "请按主表中的工作流消息包和管理摘要完成管理汇报，并回写反馈。"),
                            _text_field("执行结果", "工作流 scaffold 已创建直接汇报动作，请在飞书里补齐消息卡片、接收人和反馈回写。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W3 拍板分支工作流",
            "summary": "拍板队列出现记录后，切到拍板责任面并写出待处理动作。",
            "entry_condition": "待拍板确认 = 是",
            "route_field": "工作流路由",
            "actions": ["切换拍板责任面", "发送高管提醒", "写入拍板动作"],
            "native_goal": "把管理拍板从前端按钮推进到飞书原生工作面。",
            "receiver_binding_fields": ["拍板负责人OpenID", "汇报对象OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w3"),
                "title": "W3 拍板分支工作流",
                "steps": [
                    _checkbox_trigger("step_trigger", "待拍板确认", "进入拍板队列"),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "等待管理拍板"),
                            _role_field("当前责任角色", "拍板人"),
                            _native_action_field("当前原生动作", "管理拍板"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送拍板提醒",
                        "分析任务正在等待管理拍板",
                        [
                            "请重点查看管理摘要、工作流消息包和异常说明。",
                            "拍板结果回写后，可继续推进执行或复核动作。",
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建拍板动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "发送汇报"),
                            _action_status_field("动作状态", "待执行"),
                            _route_field("工作流路由", "等待拍板"),
                            _text_field("动作内容", "请按主表中的管理摘要完成拍板，并回写是否已拍板、拍板人、拍板时间。"),
                            _text_field("执行结果", "工作流 scaffold 已创建拍板动作，请在飞书里补齐审批链或消息卡片。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W4 执行分支工作流",
            "summary": "执行队列出现后，直接切换到执行责任面，并沉淀执行动作。",
            "entry_condition": "待执行确认 = 是",
            "route_field": "工作流路由",
            "actions": ["切换执行责任面", "写入执行动作", "延迟后再次提醒"],
            "native_goal": "让执行分支在飞书多维表格里形成可追踪的原生执行闭环。",
            "receiver_binding_fields": ["执行负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w4"),
                "title": "W4 执行分支工作流",
                "steps": [
                    _checkbox_trigger(
                        "step_trigger",
                        "待执行确认",
                        "进入执行队列",
                        extra_watch_info=[_option_condition("工作流路由", "直接执行")],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "等待执行负责人回写"),
                            _role_field("当前责任角色", "执行人"),
                            _native_action_field("当前原生动作", "执行落地"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建执行动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "创建执行任务"),
                            _action_status_field("动作状态", "待执行"),
                            _route_field("工作流路由", "直接执行"),
                            _text_field("动作内容", "请按主表中的执行模板、执行负责人和执行截止时间继续落地。"),
                            _text_field("执行结果", "工作流 scaffold 已创建执行动作，请在飞书里补齐任务分配与提醒策略。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                        next_step="step_delay",
                    ),
                    {
                        "id": "step_delay",
                        "type": "Delay",
                        "title": "等待执行进展",
                        "next": "step_notify",
                        "data": {"duration": 30},
                    },
                    _message_action(
                        "step_notify",
                        "发送执行跟进提醒",
                        "执行分支仍在进行中",
                        [
                            "如果执行已完成，请回写执行完成时间和执行状态。",
                            "如果出现阻塞，请把异常类型和异常说明更新到主表。",
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W5 复核分支工作流",
            "summary": "复核队列出现后，切到复核责任面，写入复核动作，并在延迟后再次催办。",
            "entry_condition": "待安排复核 = 是",
            "route_field": "工作流路由",
            "actions": ["切换复核责任面", "写入复核动作", "延迟后再次提醒"],
            "native_goal": "把补数复核和重跑前的复核动作统一沉淀到多维表格原生工作面。",
            "receiver_binding_fields": ["复核负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w5"),
                "title": "W5 复核分支工作流",
                "steps": [
                    _checkbox_trigger("step_trigger", "待安排复核", "进入复核队列"),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "等待复核负责人处理"),
                            _role_field("当前责任角色", "复核人"),
                            _native_action_field("当前原生动作", "安排复核"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建复核分支动作"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _action_type_field("动作类型", "创建复核任务"),
                            _action_status_field("动作状态", "待执行"),
                            _text_field("动作内容", "请按主表中的需补数条数、当前路由、证据缺口和复核 SLA 继续处理。"),
                            _text_field("执行结果", "工作流 scaffold 已创建复核动作，请在飞书里补齐负责人、复核清单和重跑说明。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                        next_step="step_delay",
                    ),
                    {
                        "id": "step_delay",
                        "type": "Delay",
                        "title": "等待复核进展",
                        "next": "step_notify",
                        "data": {"duration": 30},
                    },
                    _message_action(
                        "step_notify",
                        "发送复核跟进提醒",
                        "复核分支仍在进行中",
                        [
                            "请检查需补数事项、复核历史和异常说明是否已补全。",
                            "如果需要重跑，请在复核历史中记录原因并回写最新评审动作。",
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W6 重跑分支工作流",
            "summary": "重新分析路由出现后，保留复核上下文并创建重跑跟进记录。",
            "entry_condition": "待安排复核 = 是 且 工作流路由 = 重新分析",
            "route_field": "工作流路由",
            "actions": ["写入重跑记录", "保留旧版本说明", "提醒复核负责人继续跟进"],
            "native_goal": "把建议重跑的原因、轮次和后续动作沉淀到原生复核历史里。",
            "receiver_binding_fields": ["复核负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w6"),
                "title": "W6 重跑分支工作流",
                "steps": [
                    _checkbox_trigger(
                        "step_trigger",
                        "待安排复核",
                        "进入重跑分支",
                        extra_watch_info=[_option_condition("工作流路由", "重新分析")],
                    ),
                    _set_record_action(
                        "step_stage",
                        "分析任务",
                        [
                            _text_field("当前阶段", "重跑分支已接管"),
                            _role_field("当前责任角色", "复核人"),
                            _native_action_field("当前原生动作", "安排复核"),
                            _automation_status_field("自动化执行状态", "执行中"),
                        ],
                        next_step="step_history",
                    ),
                    _add_record_action(
                        "step_history",
                        "复核历史",
                        [
                            _text_field("复核标题", "系统记录重跑分支"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _text_field("复核结论", "当前任务已进入重新分析分支，请保留旧版本结论并补写重跑原因。"),
                            _route_field("工作流路由", "重新分析"),
                            _text_field("触发原因", "系统检测到当前任务需要重新分析，已由原生工作流接管。"),
                            _text_field("新旧结论差异", "请在飞书里补充本轮重跑与上轮结论的差异点。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                        next_step="step_notify",
                    ),
                    _message_action(
                        "step_notify",
                        "发送重跑提醒",
                        "分析任务已进入重新分析分支",
                        [
                            "请先记录重跑原因，再安排新的分析动作与补数计划。",
                            "完成重跑后，应回写最新评审动作、管理摘要和汇报版本号。",
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W7 动作失败补救工作流",
            "summary": "动作表出现失败记录后，立即进入失败补救与人工接管路径。",
            "entry_condition": "交付动作.动作状态 = 执行失败",
            "route_field": "工作流路由",
            "actions": ["发送失败告警", "写补救日志", "推动人工接管"],
            "native_goal": "让动作层失败不再淹没在单条记录里，而是进入独立的补救工作流。",
            "receiver_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w7"),
                "title": "W7 动作失败补救工作流",
                "steps": [
                    _select_trigger(
                        "step_trigger",
                        "动作状态",
                        "执行失败",
                        "失败动作进入补救流程",
                        table_name="交付动作",
                    ),
                    _message_action(
                        "step_notify",
                        "发送失败补救提醒",
                        "交付动作执行失败，进入补救分支",
                        [
                            "请先判断失败是否可重试，再决定是否转人工接管。",
                            "补救动作完成后，应同步回填失败原因、重试结果和主表异常状态。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "W7 动作失败补救工作流"),
                            _text_field("任务标题", "请在失败动作关联任务中查看"),
                            _text_field("节点名称", "W7 动作失败补救工作流"),
                            _text_field("触发来源", "workflow.action_failure"),
                            _action_status_field("执行状态", "执行失败"),
                            _text_field("日志摘要", "失败动作已进入补救流程。"),
                            _text_field("详细结果", "请在交付动作表确认是否重试，并在主表接续人工接管。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W8 群消息驱动工作流",
            "summary": "群命令入口把消息解析结果写入自动化日志后，这条工作流继续承接催办、复盘和复核动作。",
            "entry_condition": "自动化日志.触发来源 = im.command",
            "route_field": "工作流路由",
            "actions": ["承接群命令", "写入跟进动作", "广播处理结果"],
            "native_goal": "把群里触发的 AI/催办动作也沉淀回多维表格，而不是脱离原生可视化层。",
            "receiver_binding_fields": ["拍板负责人OpenID", "执行负责人OpenID", "复核负责人OpenID", "复盘负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w8"),
                "title": "W8 群消息驱动工作流",
                "steps": [
                    _text_trigger(
                        "step_trigger",
                        "触发来源",
                        "im.command",
                        "收到群命令中转记录",
                        table_name="自动化日志",
                    ),
                    _message_action(
                        "step_notify",
                        "发送群命令承接提醒",
                        "群命令已进入多维表格原生闭环",
                        [
                            "请在日志表查看命令内容对应的任务和处理动作。",
                            "后续的催办、复核和复盘建议继续沉淀到交付动作与自动化日志。",
                        ],
                        next_step="step_action",
                    ),
                    _add_record_action(
                        "step_action",
                        "交付动作",
                        [
                            _text_field("动作标题", "系统创建群命令跟进动作"),
                            _text_field("任务标题", "请根据群命令关联任务继续处理"),
                            _action_type_field("动作类型", "自动跟进任务"),
                            _action_status_field("动作状态", "待执行"),
                            _text_field("动作内容", "请根据群消息中的催办、复核或复盘指令继续回写主表和日志。"),
                            _text_field("执行结果", "群命令已经被工作流接住，请在飞书里补齐真实接收人和回执动作。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W9 仪表盘自动推送工作流",
            "summary": "任务归档后，自动触发一轮仪表盘汇总推送并沉淀推送日志。",
            "entry_condition": "状态 = 已归档",
            "route_field": "工作流路由",
            "actions": ["推送仪表盘摘要", "广播管理洞察", "记录推送日志"],
            "native_goal": "把汇报看板的推送动作沉淀回飞书原生工作流，支撑管理汇报节奏。",
            "receiver_binding_fields": ["汇报对象OpenID", "拍板负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w9"),
                "title": "W9 仪表盘自动推送工作流",
                "steps": [
                    _select_trigger("step_trigger", "状态", "已归档", "归档后推送仪表盘"),
                    _message_action(
                        "step_notify",
                        "发送仪表盘推送提醒",
                        "任务已归档，可推送管理仪表盘摘要",
                        [
                            "请结合管理汇报总览、证据与评审看板、交付异常看板整理本轮洞察。",
                            "建议把图表截图、管理摘要和下一步动作一并回写到归档记录。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "W9 仪表盘自动推送工作流"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _text_field("节点名称", "W9 仪表盘自动推送工作流"),
                            _text_field("触发来源", "workflow.dashboard_push"),
                            _action_status_field("执行状态", "已完成"),
                            _text_field("日志摘要", "任务已归档，系统已提示推送仪表盘摘要。"),
                            _text_field("详细结果", "请在飞书里补齐最终截图、AI 总结和发送对象。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
        {
            "name": "W10 数据资产校验工作流",
            "summary": "任务进入复核队列后，原生检查引用数据集、补数事项与责任人是否已经准备完毕。",
            "entry_condition": "待安排复核 = 是",
            "route_field": "工作流路由",
            "actions": ["提醒校验数据资产", "记录校验日志", "推动补数责任回写"],
            "native_goal": "把数据资产校验嵌到复核闭环里，避免引用数据集失真后继续流转。",
            "receiver_binding_fields": ["复核负责人OpenID"],
            "requires_member_binding": True,
            "body": {
                "client_token": _token("w10"),
                "title": "W10 数据资产校验工作流",
                "steps": [
                    _checkbox_trigger("step_trigger", "待安排复核", "进入数据资产校验队列"),
                    _message_action(
                        "step_notify",
                        "发送数据资产校验提醒",
                        "任务已进入数据资产校验节点",
                        [
                            "请检查引用数据集、数据源、需补数事项和证据链是否与当前结论一致。",
                            "如果数据源已经失效或缺失，请先补数再推进复核或重跑。",
                        ],
                        next_step="step_log",
                    ),
                    _add_record_action(
                        "step_log",
                        "自动化日志",
                        [
                            _text_field("日志标题", "W10 数据资产校验工作流"),
                            _text_field("任务标题", "请在主表查看对应分析任务"),
                            _text_field("节点名称", "W10 数据资产校验工作流"),
                            _text_field("触发来源", "workflow.data_asset_check"),
                            _action_status_field("执行状态", "已完成"),
                            _text_field("日志摘要", "系统已提示对引用数据集和补数事项做原生校验。"),
                            _text_field("详细结果", "请在主表回写校验结果，并在证据链与复核历史中沉淀结论。"),
                            _ref_field("关联记录ID", "$.step_trigger.recordId"),
                        ],
                    ),
                ],
            },
        },
    ]


def build_dashboard_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "管理汇报总览",
            "source_table_name": "分析任务",
            "focus_metrics": ["分析任务总量", "待拍板确认", "待执行确认", "待安排复核", "已异常任务数", "工作流路由分布"],
            "recommended_views": ["🧭 工作流路由", "⏳ 待拍板确认", "🚀 待执行落地", "🗓 待安排复核", "🟥 已异常任务"],
            "narrative": "适合给管理层做一屏汇报，直接回答现在有哪些任务、卡在哪、下一步谁接。 ",
            "block_specs": [
                ("tasks_total", "分析任务总量", "statistics", {"table_name": "分析任务", "count_all": True}),
                ("pending_approval", "待拍板确认", "statistics", _count_filter("分析任务", "待拍板确认", "is", True)),
                ("pending_execution", "待执行确认", "statistics", _count_filter("分析任务", "待执行确认", "is", True)),
                ("pending_review", "待安排复核", "statistics", _count_filter("分析任务", "待安排复核", "is", True)),
                ("exception_total", "异常任务数", "statistics", _count_filter("分析任务", "异常状态", "is", "已异常")),
                ("route_mix", "工作流路由分布", "pie", _count_group("分析任务", "工作流路由")),
                ("owner_mix", "业务归属分布", "column", _count_group("分析任务", "业务归属")),
                ("audience_mix", "汇报对象级别", "column", _count_group("分析任务", "汇报对象级别")),
                (
                    "narrative",
                    "汇报说明",
                    "text",
                    {
                        "text": "# 管理汇报总览\n- 看当前交付队列是否卡在拍板 / 执行 / 复核\n- 看工作流路由和业务归属是否失衡\n- 看异常任务是否需要立即人工接管"
                    },
                ),
            ],
        },
        {
            "name": "证据与评审看板",
            "source_table_name": "证据链",
            "focus_metrics": ["证据链总量", "硬证据数", "待验证证据数", "证据用途分布", "评审推荐动作分布"],
            "recommended_views": ["🧱 硬证据", "🟡 待验证", "⚠️ 风险证据", "🚀 机会证据", "🧪 评审看板"],
            "narrative": "适合给复核人和管理层看结论到底有没有证据，是否还差关键补数。 ",
            "block_specs": [
                ("evidence_total", "证据链总量", "statistics", {"table_name": "证据链", "count_all": True}),
                ("hard_evidence", "硬证据数", "statistics", _count_filter("证据链", "证据等级", "is", "硬证据")),
                ("pending_verify", "待验证证据数", "statistics", _count_filter("证据链", "证据等级", "is", "待验证")),
                ("evidence_grade", "证据等级分布", "pie", _count_group("证据链", "证据等级")),
                ("evidence_usage", "证据用途分布", "column", _count_group("证据链", "证据用途")),
                ("review_action", "评审推荐动作分布", "pie", _count_group("产出评审", "推荐动作")),
                (
                    "narrative",
                    "看板说明",
                    "text",
                    {
                        "text": "# 证据与评审看板\n- 看硬证据和待验证证据的比例\n- 看风险 / 机会 / 决策类证据是否均衡\n- 看评审动作是否正在把任务推向补数复核或重跑"
                    },
                ),
            ],
        },
        {
            "name": "交付异常看板",
            "source_table_name": "分析任务",
            "focus_metrics": ["异常任务数", "异常类型分布", "待复盘确认", "待拍板归档", "待执行归档", "待复盘归档", "待复核归档"],
            "recommended_views": ["🟥 已异常任务", "🟥 拍板滞留", "🟥 执行超期", "🟧 复核超时", "🟪 复盘滞留", "🔁 待复盘归档", "📦 归档看板"],
            "narrative": "适合做异常周报和闭环压盘，直接盯最影响交付的阻塞项。 ",
            "block_specs": [
                ("exception_total", "异常任务数", "statistics", _count_filter("分析任务", "异常状态", "is", "已异常")),
                ("exception_type", "异常类型分布", "pie", _count_group("分析任务", "异常类型", {"field_name": "异常状态", "operator": "is", "value": "已异常"})),
                ("pending_retrospective", "待复盘确认", "statistics", _count_filter("分析任务", "待复盘确认", "is", True)),
                ("archive_pending_approval", "待拍板归档", "statistics", _count_filter("交付结果归档", "归档状态", "is", "待拍板")),
                ("archive_pending_execution", "待执行归档", "statistics", _count_filter("交付结果归档", "归档状态", "is", "待执行")),
                ("archive_pending_retrospective", "待复盘归档", "statistics", _count_filter("交付结果归档", "归档状态", "is", "待复盘")),
                ("archive_pending_review", "待复核归档", "statistics", _count_filter("交付结果归档", "归档状态", "is", "待复核")),
                ("archive_status", "归档状态分布", "column", _count_group("交付结果归档", "归档状态")),
                (
                    "narrative",
                    "异常说明",
                    "text",
                    {
                        "text": "# 交付异常看板\n- 看异常是集中在拍板、执行、复核还是复盘\n- 看归档队列是否长期堆积\n- 看哪些任务已经需要人工接管或重新分析"
                    },
                ),
            ],
        },
    ]


def build_role_specs() -> list[dict[str, Any]]:
    return [
        {
            "name": "高管交付面",
            "focus_views": ["🧭 工作流路由", "👔 拍板人任务", "⏳ 待拍板确认", "🟥 已异常任务", "🚦 健康度看板"],
            "permissions_focus": ["分析任务", "综合报告", "交付动作", "交付结果归档"],
            "dashboard_focus": ["管理汇报总览", "证据与评审看板", "交付异常看板"],
            "native_goal": "高管只看管理必需的信息和仪表盘，不暴露执行噪音。",
            "config": _executive_role_config(),
        },
        {
            "name": "执行负责人工作面",
            "focus_views": ["⚙️ 执行人任务", "🚀 待执行落地", "🟥 已异常任务", "📅 任务甘特", "🧭 动作路由"],
            "permissions_focus": ["分析任务", "交付动作", "交付结果归档"],
            "dashboard_focus": ["管理汇报总览", "交付异常看板"],
            "native_goal": "执行人主要在执行动作、归档回写和异常修复上工作。",
            "config": _execution_role_config(),
        },
        {
            "name": "复核负责人工作面",
            "focus_views": ["🧪 复核人任务", "🗓 待安排复核", "🟨 需关注任务", "🧱 硬证据", "🟡 待验证", "🧪 评审看板"],
            "permissions_focus": ["分析任务", "证据链", "产出评审", "复核历史"],
            "dashboard_focus": ["证据与评审看板", "交付异常看板"],
            "native_goal": "复核人围绕证据、评审和复核历史工作，不直接暴露高管动作面。",
            "config": _review_role_config(),
        },
        {
            "name": "复盘负责人工作面",
            "focus_views": ["🔁 待进入复盘", "🟪 复盘滞留", "🔁 待复盘归档", "📦 归档看板"],
            "permissions_focus": ["分析任务", "交付结果归档"],
            "dashboard_focus": ["交付异常看板"],
            "native_goal": "复盘负责人承接执行后的归档闭环，专注待复盘任务、异常滞留与归档沉淀。",
            "config": _retrospective_role_config(),
        },
    ]


def _token(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


def _add_record_trigger(step_id: str, table_name: str, watched_field_name: str, title: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "AddRecordTrigger",
        "title": title,
        "next": None,
        "data": {"table_name": table_name, "watched_field_name": watched_field_name, "condition_list": None},
    }


def _checkbox_trigger(
    step_id: str,
    field_name: str,
    title: str,
    *,
    table_name: str = "分析任务",
    extra_watch_info: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "SetRecordTrigger",
        "title": title,
        "next": None,
        "data": {
            "table_name": table_name,
            "record_watch_conjunction": "and",
            "record_watch_info": [],
            "field_watch_info": [_bool_condition(field_name, True), *(extra_watch_info or [])],
            "trigger_control_list": [],
            "condition_list": None,
        },
    }


def _select_trigger(
    step_id: str,
    field_name: str,
    option_name: str,
    title: str,
    *,
    table_name: str = "分析任务",
    extra_watch_info: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "SetRecordTrigger",
        "title": title,
        "next": None,
        "data": {
            "table_name": table_name,
            "record_watch_conjunction": "and",
            "record_watch_info": [],
            "field_watch_info": [_option_condition(field_name, option_name), *(extra_watch_info or [])],
            "trigger_control_list": [],
            "condition_list": None,
        },
    }


def _text_trigger(
    step_id: str,
    field_name: str,
    text_value: str,
    title: str,
    *,
    table_name: str = "分析任务",
    extra_watch_info: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "SetRecordTrigger",
        "title": title,
        "next": None,
        "data": {
            "table_name": table_name,
            "record_watch_conjunction": "and",
            "record_watch_info": [],
            "field_watch_info": [_text_condition(field_name, text_value), *(extra_watch_info or [])],
            "trigger_control_list": [],
            "condition_list": None,
        },
    }


def _option_condition(field_name: str, option_name: str) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "operator": "is",
        "value": [{"value_type": "option", "value": {"name": option_name}}],
    }


def _text_condition(field_name: str, value: str) -> dict[str, Any]:
    return {"field_name": field_name, "operator": "is", "value": [{"value_type": "text", "value": value}]}


def _bool_condition(field_name: str, value: bool) -> dict[str, Any]:
    return {"field_name": field_name, "operator": "is", "value": [{"value_type": "boolean", "value": value}]}


def _reminder_trigger(
    step_id: str,
    field_name: str,
    title: str,
    *,
    table_name: str = "分析任务",
    condition_list: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "ReminderTrigger",
        "title": title,
        "next": None,
        "data": {
            "table_name": table_name,
            "field_name": field_name,
            "offset": 0,
            "unit": "DAY",
            "hour": 9,
            "minute": 0,
            "condition_list": condition_list,
        },
    }


def _set_record_action(
    step_id: str,
    table_name: str,
    field_values: list[dict[str, Any]],
    *,
    next_step: str | None,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "SetRecordAction",
        "title": "回写原生状态",
        "next": next_step,
        "data": {
            "table_name": table_name,
            "max_set_record_num": 1,
            "field_values": field_values,
            "ref_info": {"step_id": "step_trigger"},
        },
    }


def _add_record_action(step_id: str, table_name: str, field_values: list[dict[str, Any]], next_step: str | None = None) -> dict[str, Any]:
    return {
        "id": step_id,
        "type": "AddRecordAction",
        "title": f"写入{table_name}",
        "next": next_step,
        "data": {"table_name": table_name, "field_values": field_values},
    }


def _message_action(
    step_id: str,
    title: str,
    card_title: str,
    paragraphs: list[str],
    *,
    next_step: str | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for idx, paragraph in enumerate(paragraphs):
        if idx > 0:
            content.append({"value_type": "text", "value": "\n"})
        content.append({"value_type": "text", "value": paragraph})
    return {
        "id": step_id,
        "type": "LarkMessageAction",
        "title": title,
        "next": next_step,
        "data": {
            "receiver": [],
            "send_to_everyone": True,
            "title": [{"value_type": "text", "value": card_title}],
            "content": content,
            "btn_list": [
                {
                    "text": "打开对应记录",
                    "btn_action": "openLink",
                    "link": [{"value_type": "ref", "value": "$.step_trigger.recordLink"}],
                }
            ],
        },
    }


def _text_field(field_name: str, value: str) -> dict[str, Any]:
    return {"field_name": field_name, "value": [{"value_type": "text", "value": value}]}


def _ref_field(field_name: str, ref_path: str) -> dict[str, Any]:
    return {"field_name": field_name, "value": [{"value_type": "ref", "value": ref_path}]}


def _option_field(field_name: str, option_name: str) -> dict[str, Any]:
    return {"field_name": field_name, "value": [{"value_type": "option", "value": {"name": option_name}}]}


def _role_field(field_name: str, option_name: str) -> dict[str, Any]:
    return _option_field(field_name, option_name)


def _native_action_field(field_name: str, option_name: str) -> dict[str, Any]:
    return _option_field(field_name, option_name)


def _automation_status_field(field_name: str, option_name: str) -> dict[str, Any]:
    return _option_field(field_name, option_name)


def _action_status_field(field_name: str, option_name: str) -> dict[str, Any]:
    return _option_field(field_name, option_name)


def _action_type_field(field_name: str, option_name: str) -> dict[str, Any]:
    return _option_field(field_name, option_name)


def _route_field(field_name: str, option_name: str) -> dict[str, Any]:
    return _option_field(field_name, option_name)


def _count_filter(table_name: str, field_name: str, operator: str, value: Any) -> dict[str, Any]:
    return {
        "table_name": table_name,
        "count_all": True,
        "filter": {"conjunction": "and", "conditions": [{"field_name": field_name, "operator": operator, "value": value}]},
    }


def _count_group(table_name: str, field_name: str, extra_filter: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "table_name": table_name,
        "count_all": True,
        "group_by": [{"field_name": field_name, "mode": "integrated"}],
    }
    if extra_filter:
        payload["filter"] = {"conjunction": "and", "conditions": [extra_filter]}
    return payload


def _read_only_table_rule(visible_views: list[str]) -> dict[str, Any]:
    return {
        "perm": "read_only",
        "view_rule": {
            "allow_edit": False,
            "visibility": {"all_visible": False, "visible_views": visible_views},
        },
        "field_rule": {"field_perm_mode": "all_read"},
    }


def _edit_table_rule(visible_views: list[str]) -> dict[str, Any]:
    return {
        "perm": "edit",
        "view_rule": {
            "allow_edit": True,
            "visibility": {"all_visible": False, "visible_views": visible_views},
        },
        "field_rule": {"field_perm_mode": "all_edit"},
        "record_rule": {"record_operations": ["add", "delete"], "other_record_all_read": True},
    }


def _executive_role_config() -> dict[str, Any]:
    return {
        "role_name": "高管交付面",
        "role_type": "custom_role",
        "base_rule_map": {"copy": False, "download": False},
        "dashboard_rule_map": {
            "管理汇报总览": {"perm": "read_only"},
            "证据与评审看板": {"perm": "read_only"},
            "交付异常看板": {"perm": "read_only"},
        },
        "table_rule_map": {
            "分析任务": _read_only_table_rule(["🧭 工作流路由", "👔 拍板人任务", "⏳ 待拍板确认", "🟥 已异常任务"]),
            "综合报告": _read_only_table_rule(["🟢 健康报告", "🟡 关注报告", "🔴 预警报告", "🚦 健康度看板"]),
            "交付动作": _read_only_table_rule(["📣 汇报动作", "✅ 已完成动作", "❌ 失败动作"]),
            "交付结果归档": _read_only_table_rule(["📬 待汇报归档", "⏳ 待拍板归档", "🔁 待复盘归档", "📦 归档看板"]),
        },
    }


def _execution_role_config() -> dict[str, Any]:
    return {
        "role_name": "执行负责人工作面",
        "role_type": "custom_role",
        "base_rule_map": {"copy": False, "download": False},
        "dashboard_rule_map": {
            "管理汇报总览": {"perm": "read_only"},
            "证据与评审看板": {"perm": "no_perm"},
            "交付异常看板": {"perm": "read_only"},
        },
        "table_rule_map": {
            "分析任务": _filtered_edit_table_rule(
                ["⚙️ 执行人任务", "🚀 待执行落地", "🟥 已异常任务", "📅 任务甘特"],
                _execution_task_field_rule(),
                filter_field="当前责任角色",
                filter_values=["执行人"],
            ),
            "交付动作": _filtered_edit_table_rule(
                ["📣 汇报动作", "✅ 已完成动作", "❌ 失败动作", "🧭 动作路由"],
                _execution_action_field_rule(),
                filter_field="工作流路由",
                filter_values=["直接执行"],
            ),
            "交付结果归档": _filtered_edit_table_rule(
                ["🧾 待执行归档", "📦 归档看板"],
                _execution_archive_field_rule(),
                filter_field="归档状态",
                filter_values=["待执行"],
            ),
        },
    }


def _review_role_config() -> dict[str, Any]:
    return {
        "role_name": "复核负责人工作面",
        "role_type": "custom_role",
        "base_rule_map": {"copy": False, "download": False},
        "dashboard_rule_map": {
            "管理汇报总览": {"perm": "no_perm"},
            "证据与评审看板": {"perm": "read_only"},
            "交付异常看板": {"perm": "read_only"},
        },
        "table_rule_map": {
            "分析任务": _filtered_edit_table_rule(
                ["🧪 复核人任务", "🗓 待安排复核", "🟨 需关注任务", "🟥 已异常任务"],
                _review_task_field_rule(),
                filter_field="当前责任角色",
                filter_values=["复核人"],
            ),
            "证据链": _read_only_table_rule(["🧱 硬证据", "🟡 待验证", "⚠️ 风险证据", "🚀 机会证据", "🧾 证据类型看板"]),
            "产出评审": _filtered_edit_table_rule(
                ["✅ 直接采用", "🟡 补数后复核", "🔁 建议重跑", "🧪 评审看板"],
                _review_result_field_rule(),
            ),
            "复核历史": _filtered_edit_table_rule(
                ["🟡 补数复核历史", "🔁 重跑历史", "✅ 直接采用历史", "🧪 复核轮次看板"],
                _review_history_field_rule(),
            ),
        },
    }


def _retrospective_role_config() -> dict[str, Any]:
    return {
        "role_name": "复盘负责人工作面",
        "role_type": "custom_role",
        "base_rule_map": {"copy": False, "download": False},
        "dashboard_rule_map": {
            "管理汇报总览": {"perm": "no_perm"},
            "证据与评审看板": {"perm": "no_perm"},
            "交付异常看板": {"perm": "read_only"},
        },
        "table_rule_map": {
            "分析任务": _filtered_edit_table_rule(
                ["🔁 待进入复盘", "🟪 复盘滞留", "🟥 已异常任务"],
                _retrospective_task_field_rule(),
                filter_field="当前责任角色",
                filter_values=["复盘负责人"],
            ),
            "交付结果归档": _filtered_edit_table_rule(
                ["🔁 待复盘归档", "📦 归档看板"],
                _retrospective_archive_field_rule(),
                filter_field="归档状态",
                filter_values=["待复盘"],
            ),
        },
    }


def _filtered_edit_table_rule(
    visible_views: list[str],
    field_rule: dict[str, Any],
    *,
    filter_field: str | None = None,
    filter_values: list[str] | None = None,
) -> dict[str, Any]:
    record_rule: dict[str, Any] = {"record_operations": ["add", "delete"], "other_record_all_read": True}
    if filter_field and filter_values:
        record_rule["edit_filter_rule_group"] = {
            "conjunction": "and",
            "filter_rules": [
                {
                    "conjunction": "and",
                    "filters": [
                        {
                            "field_name": filter_field,
                            "operator": "contains" if len(filter_values) > 1 else "is",
                            "filter_values": filter_values,
                        }
                    ],
                }
            ],
        }
    return {
        "perm": "edit",
        "view_rule": {
            "allow_edit": True,
            "visibility": {"all_visible": False, "visible_views": visible_views},
        },
        "field_rule": field_rule,
        "record_rule": record_rule,
    }


def _specify_field_rule(
    all_fields: list[dict[str, Any]],
    edit_fields: list[str],
    read_fields: list[str],
    hidden_fields: list[str] | None = None,
) -> dict[str, Any]:
    field_perms: dict[str, str] = {}
    allowed = set(_field_names(all_fields))
    excluded = set(hidden_fields or [])
    for field_name in allowed:
        field_perms[field_name] = "read"
    for field_name in edit_fields:
        if field_name in allowed:
            field_perms[field_name] = "edit"
    for field_name in read_fields:
        if field_name in allowed:
            field_perms.setdefault(field_name, "read")
    for field_name in excluded:
        if field_name in allowed:
            field_perms[field_name] = "no_perm"
    return {"field_perm_mode": "specify", "field_perms": field_perms}


def _execution_task_field_rule() -> dict[str, Any]:
    edit_fields = [
        "执行负责人",
        "执行负责人OpenID",
        "执行截止时间",
        "当前责任人",
        "当前阶段",
        "当前原生动作",
        "自动化执行状态",
        "是否已执行落地",
        "执行完成时间",
        "异常状态",
        "异常类型",
        "异常说明",
        "归档状态",
    ]
    read_fields = [
        "任务标题",
        "任务编号",
        "状态",
        "优先级",
        "目标对象",
        "输出目的",
        "业务归属",
        "工作流路由",
        "工作流执行包",
        "成功标准",
        "约束条件",
        "最新管理摘要",
        "最新评审动作",
        "当前责任角色",
        "汇报对象",
        "汇报对象级别",
        "待执行确认",
        "待复盘确认",
        "创建时间",
        "最近更新",
    ]
    return _specify_field_rule(workflow_schema.TASK_FIELDS, edit_fields, read_fields, ["任务图像"])


def _execution_action_field_rule() -> dict[str, Any]:
    return _specify_field_rule(
        workflow_schema.ACTION_FIELDS,
        ["动作状态", "执行结果", "动作内容"],
        ["动作标题", "任务标题", "动作类型", "工作流路由", "关联记录ID", "生成时间"],
    )


def _execution_archive_field_rule() -> dict[str, Any]:
    return _specify_field_rule(
        workflow_schema.DELIVERY_ARCHIVE_FIELDS,
        ["归档状态", "执行负责人", "关联记录ID"],
        ["归档标题", "任务标题", "任务编号", "汇报版本号", "工作流路由", "最新评审动作", "一句话结论", "管理摘要", "首要动作", "汇报就绪度", "工作流消息包", "汇报对象", "复核负责人", "生成时间"],
    )


def _review_task_field_rule() -> dict[str, Any]:
    edit_fields = [
        "复核负责人",
        "复核负责人OpenID",
        "复核SLA小时",
        "建议复核时间",
        "最新评审动作",
        "最新评审摘要",
        "汇报就绪度",
        "需补数条数",
        "当前责任人",
        "当前阶段",
        "当前原生动作",
        "自动化执行状态",
        "异常状态",
        "异常类型",
        "异常说明",
        "待安排复核",
    ]
    read_fields = [
        "任务标题",
        "任务编号",
        "状态",
        "优先级",
        "目标对象",
        "输出目的",
        "业务归属",
        "工作流路由",
        "成功标准",
        "约束条件",
        "证据条数",
        "高置信证据数",
        "硬证据数",
        "待验证证据数",
        "进入CEO汇总证据数",
        "决策事项数",
        "当前责任角色",
        "汇报对象",
        "待拍板确认",
        "待复盘确认",
        "创建时间",
        "最近更新",
    ]
    return _specify_field_rule(workflow_schema.TASK_FIELDS, edit_fields, read_fields, ["任务图像"])


def _review_result_field_rule() -> dict[str, Any]:
    return _specify_field_rule(
        workflow_schema.REVIEW_FIELDS,
        ["推荐动作", "评审摘要", "真实性", "决策性", "可执行性", "闭环准备度", "需补数事项"],
        ["任务标题", "工作流路由", "生成时间", "关联记录ID"],
    )


def _review_history_field_rule() -> dict[str, Any]:
    return _specify_field_rule(
        workflow_schema.REVIEW_HISTORY_FIELDS,
        ["推荐动作", "触发原因", "复核结论", "新旧结论差异", "需补数事项"],
        ["复核标题", "任务标题", "任务编号", "复核轮次", "工作流路由", "前次评审动作", "关联记录ID", "生成时间"],
    )


def _retrospective_task_field_rule() -> dict[str, Any]:
    edit_fields = [
        "复盘负责人",
        "复盘负责人OpenID",
        "当前责任人",
        "当前阶段",
        "当前原生动作",
        "自动化执行状态",
        "是否进入复盘",
        "待复盘确认",
        "状态",
        "归档状态",
        "异常状态",
        "异常类型",
        "异常说明",
    ]
    read_fields = [
        "任务标题",
        "任务编号",
        "优先级",
        "目标对象",
        "输出目的",
        "业务归属",
        "工作流路由",
        "成功标准",
        "约束条件",
        "最新管理摘要",
        "最新评审动作",
        "汇报对象",
        "执行负责人",
        "复核负责人",
        "待执行确认",
        "待复盘确认",
        "创建时间",
        "最近更新",
    ]
    return _specify_field_rule(workflow_schema.TASK_FIELDS, edit_fields, read_fields, ["任务图像"])


def _retrospective_archive_field_rule() -> dict[str, Any]:
    return _specify_field_rule(
        workflow_schema.DELIVERY_ARCHIVE_FIELDS,
        ["归档状态", "关联记录ID"],
        ["归档标题", "任务标题", "任务编号", "汇报版本号", "工作流路由", "一句话结论", "管理摘要", "首要动作", "汇报就绪度", "工作流消息包", "汇报对象", "执行负责人", "复核负责人", "生成时间"],
    )


def _field_names(fields: list[dict[str, Any]]) -> list[str]:
    excluded_types = {
        workflow_schema.CREATED_TIME_FIELD_TYPE,
        workflow_schema.MODIFIED_TIME_FIELD_TYPE,
        workflow_schema.AUTO_NUMBER_FIELD_TYPE,
    }
    names: list[str] = []
    for field in fields:
        field_name = str(field.get("field_name") or "").strip()
        if not field_name:
            continue
        if field.get("type") in excluded_types:
            continue
        names.append(field_name)
    return names
