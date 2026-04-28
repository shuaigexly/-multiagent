import { describe, expect, it } from "vitest";
import {
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
});
