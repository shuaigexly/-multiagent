export type WorkflowSourceKind = "task" | "review" | "action" | "archive" | "unsupported";

export interface WorkflowSelectionRecord {
  recordId: string;
  fields: Record<string, unknown>;
}

export interface WorkflowTableIds {
  task?: string;
  review?: string;
  action?: string;
  archive?: string;
}

export interface WorkflowTaskLocator {
  sourceKind: WorkflowSourceKind;
  sourceLabel: string;
  taskRecordId: string;
  taskTitle: string;
}

export type WorkflowResolutionMode = "selected-task-record" | "related-record-id" | "task-title-fallback" | "unresolved";

export interface WorkflowResolutionDebug {
  sourceKind: WorkflowSourceKind;
  sourceLabel: string;
  selectedRecordId: string;
  selectedTaskTitle: string;
  taskRecordIdCandidate: string;
  taskTitleCandidate: string;
  resolutionMode: WorkflowResolutionMode;
  resolutionLabel: string;
  issues: string[];
}

export interface WorkflowSummaryItem {
  label: string;
  value: string;
}

export interface WorkflowSnapshotLike {
  recordId: string;
  fields: Record<string, unknown>;
}

export interface WorkflowRelationItem {
  key: string;
  tableLabel: string;
  title: string;
  status: string;
  route: string;
  summary: string;
  chips: string[];
}

export interface WorkflowRelationSection {
  key: "review" | "action" | "archive";
  label: string;
  count: number;
  emptyText: string;
  items: WorkflowRelationItem[];
}

function textValue(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item.trim();
        if (typeof item === "number") return String(item);
        if (item && typeof item === "object") {
          const candidate = item as Record<string, unknown>;
          return textValue(candidate.text ?? candidate.name ?? candidate.id ?? "");
        }
        return "";
      })
      .filter(Boolean)
      .join(" / ");
  }
  if (value && typeof value === "object") {
    const candidate = value as Record<string, unknown>;
    return textValue(candidate.text ?? candidate.name ?? candidate.value ?? candidate.id ?? "");
  }
  return "";
}

export function getWorkflowSourceKind(tableId: string | null, tableIds: WorkflowTableIds): WorkflowSourceKind {
  if (!tableId) return "unsupported";
  if (tableId === tableIds.task) return "task";
  if (tableId === tableIds.review) return "review";
  if (tableId === tableIds.action) return "action";
  if (tableId === tableIds.archive) return "archive";
  return "unsupported";
}

export function workflowSourceLabel(sourceKind: WorkflowSourceKind): string {
  switch (sourceKind) {
    case "task":
      return "分析任务";
    case "review":
      return "产出评审";
    case "action":
      return "交付动作";
    case "archive":
      return "交付结果归档";
    default:
      return "非工作流表";
  }
}

export function buildTaskLocator(
  sourceKind: WorkflowSourceKind,
  selectionRecord: WorkflowSelectionRecord | null,
  selectedRecordId: string | null,
): WorkflowTaskLocator {
  const sourceLabel = workflowSourceLabel(sourceKind);
  const fallbackTitle = textValue(selectionRecord?.fields["任务标题"]);
  if (sourceKind === "task") {
    return {
      sourceKind,
      sourceLabel,
      taskRecordId: selectionRecord?.recordId || selectedRecordId || "",
      taskTitle: fallbackTitle,
    };
  }
  return {
    sourceKind,
    sourceLabel,
    taskRecordId: textValue(selectionRecord?.fields["关联记录ID"]),
    taskTitle: fallbackTitle,
  };
}

export function matchesTaskRecord(record: WorkflowSelectionRecord, locator: WorkflowTaskLocator): boolean {
  if (locator.taskRecordId && record.recordId === locator.taskRecordId) return true;
  if (locator.taskTitle && textValue(record.fields["任务标题"]) === locator.taskTitle) return true;
  return false;
}

export function matchesRelatedRecord(record: WorkflowSelectionRecord, locator: WorkflowTaskLocator): boolean {
  const relatedRecordId = textValue(record.fields["关联记录ID"]);
  if (locator.taskRecordId && relatedRecordId === locator.taskRecordId) return true;
  if (locator.taskTitle && textValue(record.fields["任务标题"]) === locator.taskTitle) return true;
  return false;
}

export function buildResolutionDebug(
  sourceKind: WorkflowSourceKind,
  selectionRecord: WorkflowSelectionRecord | null,
  locator: WorkflowTaskLocator,
  matchedTask: WorkflowSelectionRecord | null,
): WorkflowResolutionDebug {
  const selectedTaskTitle = textValue(selectionRecord?.fields["任务标题"]);
  const issues: string[] = [];

  if (sourceKind !== "task" && !locator.taskRecordId) {
    issues.push("缺少「关联记录ID」");
  }
  if (!locator.taskTitle) {
    issues.push("缺少「任务标题」");
  }

  let resolutionMode: WorkflowResolutionMode = "unresolved";
  let resolutionLabel = "未命中主任务";

  if (matchedTask) {
    if (sourceKind === "task") {
      resolutionMode = "selected-task-record";
      resolutionLabel = "当前主表记录";
    } else if (locator.taskRecordId && matchedTask.recordId === locator.taskRecordId) {
      resolutionMode = "related-record-id";
      resolutionLabel = "通过关联记录ID回溯";
    } else if (locator.taskTitle) {
      resolutionMode = "task-title-fallback";
      resolutionLabel = "通过任务标题兜底";
    }
  } else {
    issues.push("未找到对应分析任务");
  }

  return {
    sourceKind,
    sourceLabel: locator.sourceLabel,
    selectedRecordId: selectionRecord?.recordId || "",
    selectedTaskTitle,
    taskRecordIdCandidate: locator.taskRecordId,
    taskTitleCandidate: locator.taskTitle,
    resolutionMode,
    resolutionLabel,
    issues,
  };
}

export function buildSourceContextItems(
  sourceKind: WorkflowSourceKind,
  selectionRecord: WorkflowSelectionRecord | null,
): WorkflowSummaryItem[] {
  if (!selectionRecord) return [];

  const fields = selectionRecord.fields;
  const pushIfPresent = (label: string, value: unknown) => {
    const normalized = textValue(value);
    return normalized ? { label, value: normalized } : null;
  };

  const items: Array<WorkflowSummaryItem | null> = [
    { label: "来源表", value: workflowSourceLabel(sourceKind) },
    { label: "记录ID", value: selectionRecord.recordId || "缺失" },
  ];

  if (sourceKind === "task") {
    items.push(pushIfPresent("任务状态", fields["状态"]));
    items.push(pushIfPresent("当前阶段", fields["当前阶段"]));
    items.push(pushIfPresent("工作流路由", fields["工作流路由"]));
  } else if (sourceKind === "review") {
    items.push(pushIfPresent("推荐动作", fields["推荐动作"]));
    items.push(pushIfPresent("工作流路由", fields["工作流路由"]));
    items.push(pushIfPresent("需补数事项", fields["需补数事项"]));
  } else if (sourceKind === "action") {
    items.push(pushIfPresent("动作类型", fields["动作类型"]));
    items.push(pushIfPresent("动作状态", fields["动作状态"]));
    items.push(pushIfPresent("工作流路由", fields["工作流路由"]));
  } else if (sourceKind === "archive") {
    items.push(pushIfPresent("归档状态", fields["归档状态"]));
    items.push(pushIfPresent("工作流路由", fields["工作流路由"]));
    items.push(pushIfPresent("最新评审动作", fields["最新评审动作"]));
  }

  return items.filter((item): item is WorkflowSummaryItem => Boolean(item));
}

function pushChip(chips: string[], value: unknown) {
  const normalized = textValue(value);
  if (normalized) chips.push(normalized);
}

function buildRelationItem(
  key: string,
  tableLabel: string,
  record: WorkflowSnapshotLike,
  config: {
    titleFields: string[];
    statusFields: string[];
    routeFields: string[];
    summaryFields: string[];
    chipFields: string[];
  },
): WorkflowRelationItem {
  const pickFirst = (fieldNames: string[]) =>
    fieldNames
      .map((fieldName) => textValue(record.fields[fieldName]))
      .find(Boolean) || "";

  const chips: string[] = [];
  config.chipFields.forEach((fieldName) => pushChip(chips, record.fields[fieldName]));

  return {
    key: `${key}:${record.recordId}`,
    tableLabel,
    title: pickFirst(config.titleFields) || "未命名记录",
    status: pickFirst(config.statusFields) || "未标注状态",
    route: pickFirst(config.routeFields) || "未标注路由",
    summary: pickFirst(config.summaryFields) || "暂无摘要",
    chips: chips.slice(0, 4),
  };
}

export function buildRelationSections(
  review: WorkflowSnapshotLike | null,
  actions: WorkflowSnapshotLike[],
  archives: WorkflowSnapshotLike[],
): WorkflowRelationSection[] {
  const reviewItems = review
    ? [
        buildRelationItem("review", "产出评审", review, {
          titleFields: ["任务标题", "评审结论", "推荐动作"],
          statusFields: ["评审状态", "推荐动作", "工作流路由"],
          routeFields: ["工作流路由", "推荐动作"],
          summaryFields: ["评审摘要", "需补数事项", "评审结论"],
          chipFields: ["推荐动作", "工作流路由", "需补数事项"],
        }),
      ]
    : [];

  const actionItems = actions.map((record) =>
    buildRelationItem("action", "交付动作", record, {
      titleFields: ["动作标题", "动作类型", "任务标题"],
      statusFields: ["动作状态", "执行状态", "工作流路由"],
      routeFields: ["工作流路由", "动作类型"],
      summaryFields: ["动作说明", "执行反馈", "补充说明"],
      chipFields: ["动作类型", "动作状态", "当前责任角色", "工作流路由"],
    }),
  );

  const archiveItems = archives.map((record) =>
    buildRelationItem("archive", "交付结果归档", record, {
      titleFields: ["归档标题", "任务标题", "最新评审动作"],
      statusFields: ["归档状态", "最新评审动作", "工作流路由"],
      routeFields: ["工作流路由", "最新评审动作"],
      summaryFields: ["归档摘要", "复盘结论", "后续动作"],
      chipFields: ["归档状态", "最新评审动作", "工作流路由"],
    }),
  );

  return [
    {
      key: "review",
      label: "评审对象",
      count: reviewItems.length,
      emptyText: "还没有命中关联评审记录。",
      items: reviewItems,
    },
    {
      key: "action",
      label: "动作对象",
      count: actionItems.length,
      emptyText: "还没有命中关联动作记录。",
      items: actionItems,
    },
    {
      key: "archive",
      label: "归档对象",
      count: archiveItems.length,
      emptyText: "还没有命中关联归档记录。",
      items: archiveItems,
    },
  ];
}
