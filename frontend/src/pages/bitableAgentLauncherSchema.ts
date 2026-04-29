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

export function buildLauncherRecordFields(
  fields: LauncherFieldMeta[],
  input: LauncherPayloadInput,
): Record<string, IOpenCellValue> {
  const fieldByName = new Map(fields.map((field) => [field.name, field]));
  const cellPayload: Record<string, IOpenCellValue> = {};

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

  const title = input.title.trim();
  setTextIfExists("任务标题", title);
  setSelectIfExists("分析维度", input.dimension);
  setSelectIfExists("优先级", input.priority);
  setSelectIfExists("输出目的", input.outputPurpose);
  setTextIfExists("背景说明", input.description.trim() || `用户在 plugin 内提交：${title}`);
  setSelectIfExists("状态", "待分析");
  setTextIfExists("当前阶段", "用户从插件提交");
  setNumberIfExists("进度", 0);
  setSelectIfExists("任务来源", LAUNCHER_TASK_SOURCE);

  return cellPayload;
}
