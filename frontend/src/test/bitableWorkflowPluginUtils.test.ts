import { describe, expect, it } from "vitest";
import {
  buildTraceChainItems,
  buildRelationSections,
  buildSourceContextItems,
  buildResolutionDebug,
  buildTaskLocator,
  getWorkflowSourceKind,
  matchesRelatedRecord,
  matchesTaskRecord,
  workflowSourceLabel,
} from "../pages/bitableWorkflowPluginUtils";

describe("bitable workflow plugin utils", () => {
  it("resolves supported workflow tables by table id", () => {
    const tableIds = { task: "tbl_task", review: "tbl_review", action: "tbl_action", archive: "tbl_archive" };
    expect(getWorkflowSourceKind("tbl_task", tableIds)).toBe("task");
    expect(getWorkflowSourceKind("tbl_review", tableIds)).toBe("review");
    expect(getWorkflowSourceKind("tbl_action", tableIds)).toBe("action");
    expect(getWorkflowSourceKind("tbl_archive", tableIds)).toBe("archive");
    expect(getWorkflowSourceKind("tbl_other", tableIds)).toBe("unsupported");
    expect(workflowSourceLabel("archive")).toBe("交付结果归档");
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
});
