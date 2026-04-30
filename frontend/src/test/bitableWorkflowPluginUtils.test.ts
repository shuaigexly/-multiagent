import { describe, expect, it } from "vitest";
import {
  buildTraceChainItems,
  buildRelationSections,
  buildSourceContextItems,
  buildResolutionDebug,
  buildResolvedRelationLocator,
  buildTaskLocator,
  getWorkflowSourceKind,
  matchesRelatedRecord,
  matchesTaskRecord,
  normalizeWorkflowPage,
  normalizeWorkflowRecordFields,
  normalizeWorkflowRecordId,
  resolveAgentFocusKey,
  workflowSourceLabel,
} from "../pages/bitableWorkflowPluginUtils";

describe("bitable workflow plugin utils", () => {
  it("resolves supported workflow tables by table id", () => {
    const tableIds = { task: "tbl_task", review: "tbl_review", action: "tbl_action", archive: "tbl_archive", automation_log: "tbl_log" };
    expect(getWorkflowSourceKind("tbl_task", tableIds)).toBe("task");
    expect(getWorkflowSourceKind("tbl_review", tableIds)).toBe("review");
    expect(getWorkflowSourceKind("tbl_action", tableIds)).toBe("action");
    expect(getWorkflowSourceKind("tbl_archive", tableIds)).toBe("archive");
    expect(getWorkflowSourceKind("tbl_log", tableIds)).toBe("log");
    expect(getWorkflowSourceKind("tbl_other", tableIds)).toBe("unsupported");
    expect(workflowSourceLabel("archive")).toBe("交付结果归档");
    expect(workflowSourceLabel("log")).toBe("自动化日志");
  });

  it("builds task locator from related-table records with record id priority", () => {
    const locator = buildTaskLocator(
      "action",
      { recordId: "rec_action", fields: { 任务标题: "增长分析", 关联记录ID: "rec_task_1" } },
      "rec_action",
    );
    expect(locator.taskRecordId).toBe("rec_task_1");
    expect(locator.taskTitle).toBe("增长分析");
    expect(locator.sourceLabel).toBe("交付动作");
  });

  it("matches task and related rows by record id or fallback title", () => {
    const locator = buildTaskLocator(
      "review",
      { recordId: "rec_review", fields: { 任务标题: "经营诊断", 关联记录ID: "rec_task_2" } },
      "rec_review",
    );
    expect(matchesTaskRecord({ recordId: "rec_task_2", fields: { 任务标题: "别的标题" } }, locator)).toBe(true);
    expect(matchesRelatedRecord({ recordId: "rec_archive", fields: { 关联记录ID: "rec_task_2" } }, locator)).toBe(true);

    const titleOnlyLocator = buildTaskLocator(
      "archive",
      { recordId: "rec_archive", fields: { 任务标题: "复盘任务", 关联记录ID: "" } },
      "rec_archive",
    );
    expect(matchesTaskRecord({ recordId: "rec_task_x", fields: { 任务标题: "复盘任务" } }, titleOnlyLocator)).toBe(true);
    expect(matchesRelatedRecord({ recordId: "rec_action_x", fields: { 任务标题: "复盘任务" } }, titleOnlyLocator)).toBe(true);
  });

  it("preserves resolved task record id for related table lookups", () => {
    const locator = buildTaskLocator(
      "action",
      { recordId: "rec_action", fields: { 任务标题: "经营诊断", 关联记录ID: "rec_task_2" } },
      "rec_action",
    );
    const relationLocator = buildResolvedRelationLocator(locator, {
      recordId: "rec_task_2",
      fields: { 任务标题: "经营诊断主任务" },
    });

    expect(relationLocator.taskRecordId).toBe("rec_task_2");
    expect(relationLocator.taskTitle).toBe("经营诊断主任务");
    expect(matchesRelatedRecord({ recordId: "rec_review", fields: { 关联记录ID: "rec_task_2" } }, relationLocator)).toBe(true);
  });

  it("describes resolution path and unresolved issues", () => {
    const selectionRecord = { recordId: "rec_review", fields: { 任务标题: "经营诊断", 关联记录ID: "rec_task_2" } };
    const locator = buildTaskLocator("review", selectionRecord, "rec_review");

    const matchedById = buildResolutionDebug(
      "review",
      selectionRecord,
      locator,
      { recordId: "rec_task_2", fields: { 任务标题: "别的标题" } },
    );
    expect(matchedById.resolutionMode).toBe("related-record-id");
    expect(matchedById.resolutionLabel).toContain("关联记录ID");

    const unresolved = buildResolutionDebug(
      "archive",
      { recordId: "rec_archive", fields: { 任务标题: "", 关联记录ID: "" } },
      buildTaskLocator("archive", { recordId: "rec_archive", fields: { 任务标题: "", 关联记录ID: "" } }, "rec_archive"),
      null,
    );
    expect(unresolved.resolutionMode).toBe("unresolved");
    expect(unresolved.issues).toContain("缺少「关联记录ID」");
    expect(unresolved.issues).toContain("缺少「任务标题」");
  });

  it("builds source context items for related workflow rows", () => {
    const actionItems = buildSourceContextItems("action", {
      recordId: "rec_action",
      fields: { 动作类型: "发送汇报", 动作状态: "待执行", 工作流路由: "直接汇报" },
    });
    expect(actionItems.map((item) => item.label)).toContain("动作类型");
    expect(actionItems.map((item) => item.value)).toContain("发送汇报");

    const archiveItems = buildSourceContextItems("archive", {
      recordId: "rec_archive",
      fields: { 归档状态: "待复盘", 工作流路由: "直接执行", 最新评审动作: "补数后复核" },
    });
    expect(archiveItems.map((item) => item.label)).toContain("归档状态");
    expect(archiveItems.map((item) => item.value)).toContain("待复盘");

    const logItems = buildSourceContextItems("log", {
      recordId: "rec_log",
      fields: { 节点名称: "Wave 1 · 数据分析师", 执行状态: "执行中", 触发来源: "agent.started" },
    });
    expect(logItems.map((item) => item.label)).toContain("节点名称");
    expect(logItems.map((item) => item.value)).toContain("执行中");
  });

  it("builds related object sections with readable summaries", () => {
    const sections = buildRelationSections(
      {
        recordId: "rec_review",
        fields: {
          任务标题: "经营诊断",
          推荐动作: "补数后复核",
          工作流路由: "复核流",
          需补数事项: "补齐投放成本",
        },
      },
      [
        {
          recordId: "rec_action",
          fields: {
            动作类型: "发送汇报",
            动作状态: "待执行",
            工作流路由: "直接汇报",
            动作说明: "向老板发送日报",
            当前责任角色: "交付经理",
          },
        },
      ],
      [
        {
          recordId: "rec_archive",
          fields: {
            任务标题: "经营诊断",
            归档状态: "待复盘",
            最新评审动作: "补数后复核",
            归档摘要: "等待复盘材料",
          },
        },
      ],
    );

    expect(sections[0].label).toBe("评审对象");
    expect(sections[0].items[0].status).toBe("补数后复核");
    expect(sections[1].items[0].title).toBe("发送汇报");
    expect(sections[1].items[0].chips).toContain("交付经理");
    expect(sections[2].items[0].summary).toBe("等待复盘材料");
  });

  it("builds trace chain nodes for resolved and unresolved paths", () => {
    const resolved = buildTraceChainItems(
      "action",
      { recordId: "rec_action", fields: { 任务标题: "经营诊断", 动作类型: "发送汇报" } },
      { recordId: "rec_task", fields: { 任务标题: "经营诊断" } },
      { recordId: "rec_review", fields: { 推荐动作: "补数后复核", 工作流路由: "复核流" } },
      [{ recordId: "rec_action_1", fields: { 动作类型: "发送汇报", 动作状态: "待执行" } }],
      [{ recordId: "rec_archive_1", fields: { 归档状态: "待复盘", 最新评审动作: "补数后复核" } }],
      {
        sourceKind: "action",
        sourceLabel: "交付动作",
        selectedRecordId: "rec_action",
        selectedTaskTitle: "经营诊断",
        taskRecordIdCandidate: "rec_task",
        taskTitleCandidate: "经营诊断",
        resolutionMode: "related-record-id",
        resolutionLabel: "通过关联记录ID回溯",
        issues: [],
      },
    );
    expect(resolved.map((item) => item.key)).toEqual(["source", "task", "review", "action", "archive"]);
    expect(resolved[1].caption).toContain("关联记录ID");

    const unresolved = buildTraceChainItems(
      "review",
      { recordId: "rec_review", fields: { 任务标题: "" } },
      null,
      null,
      [],
      [],
      {
        sourceKind: "review",
        sourceLabel: "产出评审",
        selectedRecordId: "rec_review",
        selectedTaskTitle: "",
        taskRecordIdCandidate: "",
        taskTitleCandidate: "",
        resolutionMode: "unresolved",
        resolutionLabel: "未命中主任务",
        issues: ["缺少「关联记录ID」"],
      },
    );
    expect(unresolved[1].label).toBe("主任务未命中");
    expect(unresolved[1].caption).toContain("关联记录ID");
  });

  it("adds native automation logs to trace chain when available", () => {
    const nodes = buildTraceChainItems(
      "log",
      { recordId: "rec_log", fields: { 任务标题: "经营诊断", 节点名称: "Wave 1 · 数据分析师" } },
      { recordId: "rec_task", fields: { 任务标题: "经营诊断" } },
      null,
      [],
      [],
      {
        sourceKind: "log",
        sourceLabel: "自动化日志",
        selectedRecordId: "rec_log",
        selectedTaskTitle: "经营诊断",
        taskRecordIdCandidate: "rec_task",
        taskTitleCandidate: "经营诊断",
        resolutionMode: "related-record-id",
        resolutionLabel: "通过关联记录ID回溯",
        issues: [],
      },
      [{ recordId: "rec_log", fields: { 节点名称: "Wave 1 · 数据分析师", 执行状态: "执行中" } }],
    );

    expect(nodes.map((item) => item.key)).toEqual(["source", "task", "log"]);
    expect(nodes[2].label).toContain("原生日志");
    expect(nodes[2].title).toBe("Wave 1 · 数据分析师");
  });

  it("auto-focuses the running agent unless the user pinned another one", () => {
    const agents = [
      { key: "data_analyst", status: "done" },
      { key: "finance_advisor", status: "running" },
      { key: "ceo_assistant", status: "pending" },
    ];

    expect(resolveAgentFocusKey(agents, "data_analyst", false)).toBe("finance_advisor");
    expect(resolveAgentFocusKey(agents, "data_analyst", true)).toBe("data_analyst");
    expect(resolveAgentFocusKey(agents, "missing", true)).toBe("finance_advisor");
  });

  it("normalizes malformed Bitable page responses before sidebar scans", () => {
    expect(normalizeWorkflowPage({ records: [{ id: "rec_1" }], hasMore: 1, pageToken: " next " })).toEqual({
      records: [{ id: "rec_1" }],
      hasMore: true,
      pageToken: "next",
    });
    expect(normalizeWorkflowPage({ records: [], hasMore: "false", pageToken: "   " })).toEqual({
      records: [],
      hasMore: false,
      pageToken: undefined,
    });
    expect(normalizeWorkflowPage({ records: undefined, hasMore: false, pageToken: 123 })).toEqual({
      records: [],
      hasMore: false,
      pageToken: undefined,
    });
    expect(normalizeWorkflowPage(null)).toEqual({
      records: [],
      hasMore: false,
      pageToken: undefined,
    });
  });

  it("normalizes record ids and field maps from SDK variants", () => {
    expect(normalizeWorkflowRecordId({ recordId: " rec_1 " })).toBe("rec_1");
    expect(normalizeWorkflowRecordId({ id: " rec_2 " })).toBe("rec_2");
    expect(normalizeWorkflowRecordId({ recordId: "", id: "" }, " rec_fallback ")).toBe("rec_fallback");
    expect(normalizeWorkflowRecordId({ fields: {} })).toBe("");
    expect(normalizeWorkflowRecordFields({ fields: { fld_title: "增长诊断" } })).toEqual({ fld_title: "增长诊断" });
    expect(normalizeWorkflowRecordFields({ fields: null })).toEqual({});
  });
});
