"""Base surface regression tests: keep the default Bitable workspace compact."""


def test_curated_view_plan_keeps_bitable_surface_compact():
    from app.bitable_workflow.runner import _build_curated_view_plan

    plan = _build_curated_view_plan(
        task_tid="tbl_task",
        output_tid="tbl_output",
        report_tid="tbl_report",
        evidence_tid="tbl_evidence",
        review_tid="tbl_review",
        action_tid="tbl_action",
        review_history_tid="tbl_review_history",
        archive_tid="tbl_archive",
        automation_log_tid="tbl_log",
    )
    names = [item[1] for item in plan]

    assert len(plan) <= 24
    assert len(names) == len(set(names))
    for required in {
        "🧭 工作流路由",
        "⏳ 待拍板确认",
        "🚀 待执行落地",
        "🗓 待安排复核",
        "🔁 待进入复盘",
        "🟥 已异常任务",
        "📥 需求收集表",
        "🧱 硬证据",
        "🟡 待验证",
        "🧪 评审看板",
        "🧭 动作路由",
        "🔁 待复盘归档",
        "📦 归档看板",
        "🪵 节点日志看板",
    }:
        assert required in names

    noisy_views = {
        "🔥 P0 紧急",
        "📌 P1 高优",
        "📊 状态看板",
        "📇 任务画册",
        "🟢 健康岗位",
        "🔴 预警报告",
        "⏭ 跳过日志",
        "🧩 汇报模板",
    }
    assert noisy_views.isdisjoint(names)


def test_native_specs_do_not_reference_removed_bitable_views():
    from app.bitable_workflow.native_specs import build_dashboard_specs, build_role_specs
    from app.bitable_workflow.runner import _build_curated_view_plan

    created_names = {
        item[1]
        for item in _build_curated_view_plan(
            task_tid="tbl_task",
            output_tid="tbl_output",
            report_tid="tbl_report",
            evidence_tid="tbl_evidence",
            review_tid="tbl_review",
            action_tid="tbl_action",
            review_history_tid="tbl_review_history",
            archive_tid="tbl_archive",
            automation_log_tid="tbl_log",
        )
    }

    referenced: set[str] = set()
    for dashboard in build_dashboard_specs():
        referenced.update(dashboard["recommended_views"])

    for role in build_role_specs():
        referenced.update(role["focus_views"])
        for rule in role["config"]["table_rule_map"].values():
            referenced.update(rule["view_rule"]["visibility"]["visible_views"])

    assert referenced - created_names == set()
