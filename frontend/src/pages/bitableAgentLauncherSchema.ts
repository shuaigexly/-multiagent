import { IOpenSegmentType, type IOpenCellValue, type IOpenSingleSelect, type IOpenTextSegment } from "@lark-base-open/js-sdk";

export const LAUNCHER_DIMENSIONS = [
  "综合分析",
  "内容战略",
  "数据复盘",
  "增长优化",
  "产品规划",
  "运营诊断",
] as const;

export const LAUNCHER_PRIORITIES = [
  { value: "P0 紧急", color: "bg-rose-100 text-rose-700 border-rose-200" },
  { value: "P1 高", color: "bg-orange-100 text-orange-700 border-orange-200" },
  { value: "P2 中", color: "bg-sky-100 text-sky-700 border-sky-200" },
  { value: "P3 低", color: "bg-slate-100 text-slate-700 border-slate-200" },
] as const;

export const LAUNCHER_OUTPUT_PURPOSES = [
  "经营诊断",
  "管理决策",
  "执行跟进",
  "汇报展示",
  "补数核验",
] as const;

export const LAUNCHER_TASK_SOURCE = "手工创建";
export const LAUNCHER_INITIAL_WORKFLOW_CONTRACT = {
  responsibilityRole: "系统调度",
  responsibilityOwner: "系统",
  nativeAction: "等待分析完成",
  exceptionStatus: "正常",
  exceptionType: "无",
  exceptionNote: "",
  automationStatus: "未触发",
} as const;

export interface LauncherFieldMeta {
  id: string;
  name: string;
  property?: unknown;
}

interface SelectFieldProperty {
  options?: Array<{ id: string; name: string }>;
}

interface LauncherPayloadInput {
  title: string;
  description: string;
  dimension: typeof LAUNCHER_DIMENSIONS[number];
  priority: typeof LAUNCHER_PRIORITIES[number]["value"];
  outputPurpose: typeof LAUNCHER_OUTPUT_PURPOSES[number];
}

function recordLike(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

export function normalizeLauncherRecordId(value: unknown): string {
  const objectValue = recordLike(value);
  const dataValue = recordLike(objectValue?.data);
  const candidates = [
    value,
    objectValue?.recordId,
    objectValue?.record_id,
    objectValue?.id,
    dataValue?.recordId,
    dataValue?.record_id,
    dataValue?.id,
  ];
  for (const candidate of candidates) {
    if (typeof candidate === "string" || typeof candidate === "number") {
      const normalized = String(candidate).trim();
      if (normalized) return normalized;
    }
  }
  throw new Error("新增记录未返回有效 recordId");
}

export function buildLauncherRecordFields(
  fields: LauncherFieldMeta[],
  input: LauncherPayloadInput,
): Record<string, IOpenCellValue> {
  const fieldByName = new Map(fields.map((field) => [field.name, field]));
  const cellPayload: Record<string, IOpenCellValue> = {};

  const requireField = (name: string): LauncherFieldMeta => {
    const field = fieldByName.get(name);
    if (!field) {
      throw new Error(`缺少必需字段「${name}」`);
    }
    return field;
  };

  const textCell = (value: string): IOpenTextSegment[] => [
    { type: IOpenSegmentType.Text, text: value },
  ];

  const selectCell = (field: LauncherFieldMeta, value: string): IOpenSingleSelect => {
    const property = field.property as SelectFieldProperty | undefined;
    const option = property?.options?.find((item) => item.name === value);
    if (!option) {
      throw new Error(`字段「${field.name}」缺少选项「${value}」`);
    }
    return { id: option.id, text: option.name };
  };

  const setTextIfExists = (name: string, value: string) => {
    const field = fieldByName.get(name);
    if (field) cellPayload[field.id] = textCell(value);
  };
  const setSelectIfExists = (name: string, value: string) => {
    const field = fieldByName.get(name);
    if (field) cellPayload[field.id] = selectCell(field, value);
  };
  const setNumberIfExists = (name: string, value: number) => {
    const field = fieldByName.get(name);
    if (field) cellPayload[field.id] = value;
  };
  const setCheckboxIfExists = (name: string, value: boolean) => {
    const field = fieldByName.get(name);
    if (field) cellPayload[field.id] = value;
  };

  const title = input.title.trim();
  if (!title) {
    throw new Error("任务标题不能为空");
  }
  cellPayload[requireField("任务标题").id] = textCell(title);
  setSelectIfExists("分析维度", input.dimension);
  setSelectIfExists("优先级", input.priority);
  setSelectIfExists("输出目的", input.outputPurpose);
  setTextIfExists("背景说明", input.description.trim() || `用户在 plugin 内提交：${title}`);
  setSelectIfExists("状态", "待分析");
  setTextIfExists("当前阶段", "用户从插件提交");
  setNumberIfExists("进度", 0);
  setSelectIfExists("任务来源", LAUNCHER_TASK_SOURCE);
  setSelectIfExists("当前责任角色", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.responsibilityRole);
  setTextIfExists("当前责任人", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.responsibilityOwner);
  setSelectIfExists("当前原生动作", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.nativeAction);
  setSelectIfExists("异常状态", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.exceptionStatus);
  setSelectIfExists("异常类型", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.exceptionType);
  setTextIfExists("异常说明", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.exceptionNote);
  setSelectIfExists("自动化执行状态", LAUNCHER_INITIAL_WORKFLOW_CONTRACT.automationStatus);
  [
    "待发送汇报",
    "待创建执行任务",
    "待安排复核",
    "是否已拍板",
    "待拍板确认",
    "是否已执行落地",
    "待执行确认",
    "是否进入复盘",
    "待复盘确认",
  ].forEach((name) => setCheckboxIfExists(name, false));

  return cellPayload;
}
