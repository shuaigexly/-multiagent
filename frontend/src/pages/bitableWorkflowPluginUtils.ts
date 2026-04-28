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

