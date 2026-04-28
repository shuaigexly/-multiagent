import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FilterConjunction, FilterOperator, bitable, type IGetRecordsFilterInfo } from "@lark-base-open/js-sdk";
import {
  Activity,
  CheckCircle2,
  Clock3,
  Loader2,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { API_KEY_STORAGE_KEY, getRuntimeApiKey } from "@/services/http";
import { subscribeTaskProgress, type ProgressEvent } from "@/services/workflow";
import {
  buildRelationSections,
  buildSourceContextItems,
  buildResolutionDebug,
  buildTaskLocator,
  getWorkflowSourceKind,
  matchesRelatedRecord,
  matchesTaskRecord,
  workflowSourceLabel,
  type WorkflowResolutionDebug,
  type WorkflowRelationSection,
  type WorkflowSummaryItem,
  type WorkflowSourceKind,
} from "./bitableWorkflowPluginUtils";

type StepStatus = "done" | "running" | "pending" | "error";

interface WorkflowStepDetail {
  key: string;
  title: string;
  description: string;
  status: StepStatus;
  items: string[];
  note?: string;
}

interface TaskSnapshot {
  recordId: string;
  fields: Record<string, unknown>;
}

interface LiveStepEvent {
  key: string;
  eventType: ProgressEvent["event_type"];
  stage: string;
  status: "running" | "done" | "error";
  updatedAt: string;
  detail: string;
}

interface LiveState {
  stage: string;
  progress: number;
  status: "running" | "done" | "error";
  updatedAt: string;
  tokenPreview?: string;
  activeAgent?: string;
  history: LiveStepEvent[];
  workflowSteps?: WorkflowStepDetail[];
}

interface BitableRecordValue {
  recordId?: string;
  fields: Record<string, unknown>;
}

const TASK_TABLE_NAME = "分析任务";
const REVIEW_TABLE_NAME = "产出评审";
const ACTION_TABLE_NAME = "交付动作";
const ARCHIVE_TABLE_NAME = "交付结果归档";

const WORKFLOW_DETAIL_STATUS_STYLE: Record<StepStatus, string> = {
  done: "border-emerald-200 bg-emerald-50 text-emerald-700",
  running: "border-sky-200 bg-sky-50 text-sky-700",
  pending: "border-slate-200 bg-slate-100 text-slate-600",
  error: "border-rose-200 bg-rose-50 text-rose-700",
};

const STEP_STATUS_STYLE: Record<LiveStepEvent["status"], string> = {
  running: "border-sky-200 bg-sky-50 text-sky-700",
  done: "border-emerald-200 bg-emerald-50 text-emerald-700",
  error: "border-rose-200 bg-rose-50 text-rose-700",
};

const RESOLUTION_STYLE: Record<WorkflowResolutionDebug["resolutionMode"], string> = {
  "selected-task-record": "border-emerald-200 bg-emerald-50 text-emerald-700",
  "related-record-id": "border-sky-200 bg-sky-50 text-sky-700",
  "task-title-fallback": "border-amber-200 bg-amber-50 text-amber-700",
  unresolved: "border-rose-200 bg-rose-50 text-rose-700",
};

function textValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item;
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

function numberValue(value: unknown): number {
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function safeProgress(value: unknown): number {
  const raw = numberValue(value);
  const normalized = raw <= 1 ? raw * 100 : raw;
  return Math.max(0, Math.min(100, normalized));
}

function formatRelativeTime(value: string): string {
  if (!value) return "刚刚更新";
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.max(0, Math.round(diff / 60000));
  if (minutes < 1) return "刚刚更新";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}

function formatDateValue(value: unknown): string {
  const raw = textValue(value);
  if (!raw) return "未更新";
  const parsed = Date.parse(raw);
  if (!Number.isFinite(parsed)) return raw;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(parsed));
}

function buildLiveStepEvent(event: ProgressEvent): LiveStepEvent | null {
  if (event.event_type === "agent.token") return null;
  const status =
    event.payload.step_status === "done" || event.payload.step_status === "error" || event.payload.step_status === "running"
      ? event.payload.step_status
      : event.event_type === "task.done"
        ? "done"
        : event.event_type === "task.error"
          ? "error"
          : "running";
  return {
    key: `${String(event.payload.step_key || event.event_type)}-${event.ts}`,
    eventType: event.event_type,
    stage: String(event.payload.stage || event.payload.step_title || event.event_type),
    status,
    updatedAt: event.ts,
    detail: String(event.payload.step_description || event.payload.reason || event.payload.stage || event.event_type),
  };
}

function normalizeWorkflowSteps(steps: unknown): WorkflowStepDetail[] {
  if (!Array.isArray(steps)) return [];
  return steps
    .map((item) => {
      const step = item as Record<string, unknown>;
      const status = textValue(step.status) as StepStatus;
      return {
        key: textValue(step.key),
        title: textValue(step.title) || "未命名步骤",
        description: textValue(step.description) || "等待步骤说明",
        status: ["done", "running", "pending", "error"].includes(status) ? status : "pending",
        items: Array.isArray(step.items) ? step.items.map((entry) => textValue(entry)).filter(Boolean) : [],
        note: textValue(step.note) || undefined,
      };
    })
    .filter((step) => step.key);
}

function buildWorkflowDetails(
  task: TaskSnapshot | null,
  review: TaskSnapshot | null,
  actions: TaskSnapshot[],
  archives: TaskSnapshot[],
  live: LiveState | null,
): WorkflowStepDetail[] {
  if (!task) return [];
  if (live?.workflowSteps?.length) return live.workflowSteps;

  const route = textValue(task.fields["工作流路由"]) || "待生成";
  const reviewAction = textValue(task.fields["最新评审动作"]) || textValue(review?.fields["推荐动作"]) || "待评审";
  const responsibility = textValue(task.fields["当前责任角色"]) || "系统调度";
  const nativeAction = textValue(task.fields["当前原生动作"]) || "等待分析完成";
  const actionItems = actions
    .slice(0, 4)
    .map((item) => `${textValue(item.fields["动作类型"]) || "工作流动作"} · ${textValue(item.fields["动作状态"]) || "未知"}`);

  return [
    {
      key: "intake",
      title: "第 1 步，任务接入",
      description: "定位当前选中的分析任务、对象和成功标准。",
      status: "done",
      items: [
        `任务来源：${textValue(task.fields["任务来源"]) || "未标注"}`,
        `目标对象：${textValue(task.fields["目标对象"]) || textValue(task.fields["汇报对象"]) || "未指定"}`,
        `成功标准：${textValue(task.fields["成功标准"]) || "未填写"}`,
      ],
      note: textValue(task.fields["背景说明"]) || undefined,
    },
    {
      key: "analysis",
      title: "第 2 步，七岗分析",
      description: "接收当前阶段、实时事件和步骤推进。",
      status:
        live?.status === "error"
          ? "error"
          : live?.status === "done"
            ? "done"
            : textValue(task.fields["状态"]) === "分析中"
              ? "running"
              : "pending",
      items: [live?.stage || textValue(task.fields["当前阶段"]) || "等待调度进入分析流"],
      note: live?.tokenPreview ? `${live.activeAgent ? `${live.activeAgent}：` : ""}${live.tokenPreview}` : undefined,
    },
    {
      key: "routing",
      title: "第 3 步，评审与路由",
      description: "明确推荐动作、当前责任和下一原生动作。",
      status: route !== "待生成" || reviewAction !== "待评审" ? "done" : "pending",
      items: [
        `推荐动作：${reviewAction}`,
        `工作流路由：${route}`,
        `当前责任：${responsibility}`,
        `原生动作：${nativeAction}`,
      ],
    },
    {
      key: "delivery",
      title: "第 4 步，动作沉淀",
      description: "把交付动作、归档状态和后续工作流记录沉淀下来。",
      status: actionItems.length > 0 || archives.length > 0 ? "done" : "pending",
      items: actionItems.length > 0 ? actionItems : ["等待动作沉淀"],
      note:
        archives.length > 0
          ? `归档状态：${textValue(archives[0].fields["归档状态"]) || "待补充"}`
          : undefined,
    },
  ];
}

async function resolveTableIdByName(name: string): Promise<string> {
  const table = await bitable.base.getTableByName(name);
  return table.id;
}

async function getTableFieldMap(tableId: string): Promise<Map<string, string>> {
  const table = await bitable.base.getTableById(tableId);
  const metas = await table.getFieldMetaList();
  return new Map(metas.map((meta: { id: string; name: string }) => [meta.id, meta.name]));
}

function getFieldIdByName(fieldMap: Map<string, string>, fieldName: string): string {
  for (const [fieldId, name] of fieldMap.entries()) {
    if (name === fieldName) return fieldId;
  }
  return "";
}

function mapRecordFields(record: BitableRecordValue, fieldMap: Map<string, string>): TaskSnapshot {
  const mapped: Record<string, unknown> = {};
  Object.entries(record.fields || {}).forEach(([fieldId, value]) => {
    mapped[fieldMap.get(fieldId) || fieldId] = value;
  });
  return {
    recordId: record.recordId || "",
    fields: mapped,
  };
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">{text}</div>;
}

export default function BitableWorkflowPlugin() {
  const [selection, setSelection] = useState<{ baseId: string | null; tableId: string | null; recordId: string | null }>({
    baseId: null,
    tableId: null,
    recordId: null,
  });
  const [tableIds, setTableIds] = useState<Record<string, string>>({});
  const [sourceKind, setSourceKind] = useState<WorkflowSourceKind>("unsupported");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [task, setTask] = useState<TaskSnapshot | null>(null);
  const [review, setReview] = useState<TaskSnapshot | null>(null);
  const [actions, setActions] = useState<TaskSnapshot[]>([]);
  const [archives, setArchives] = useState<TaskSnapshot[]>([]);
  const [live, setLive] = useState<LiveState | null>(null);
  const [resolutionDebug, setResolutionDebug] = useState<WorkflowResolutionDebug | null>(null);
  const [selectedRecordSnapshot, setSelectedRecordSnapshot] = useState<TaskSnapshot | null>(null);
  const unsubscribeRef = useRef<null | (() => void)>(null);
  const tableCacheRef = useRef(new Map<string, Promise<{ getRecordById(recordId: string): Promise<BitableRecordValue>; getRecordsByPage(params: { pageSize?: number; pageToken?: number }): Promise<{ records: BitableRecordValue[]; hasMore: boolean; pageToken?: number }>; }>>());
  const fieldMapCacheRef = useRef(new Map<string, Promise<Map<string, string>>>());

  const getCachedTable = useCallback((tableId: string) => {
    const cached = tableCacheRef.current.get(tableId);
    if (cached) return cached;
    const promise = bitable.base.getTableById(tableId);
    tableCacheRef.current.set(tableId, promise);
    return promise;
  }, []);

  const getCachedFieldMap = useCallback((tableId: string) => {
    const cached = fieldMapCacheRef.current.get(tableId);
    if (cached) return cached;
    const promise = getTableFieldMap(tableId);
    fieldMapCacheRef.current.set(tableId, promise);
    return promise;
  }, []);

  const getMappedRecordById = useCallback(async (tableId: string, recordId: string): Promise<TaskSnapshot> => {
    const [table, fieldMap] = await Promise.all([getCachedTable(tableId), getCachedFieldMap(tableId)]);
    const record = await table.getRecordById(recordId);
    return mapRecordFields(record, fieldMap);
  }, [getCachedFieldMap, getCachedTable]);

  const collectMappedRecords = useCallback(async (
    tableId: string,
    predicate: (record: TaskSnapshot) => boolean,
    limit: number,
    seed: TaskSnapshot[] = [],
    filter?: IGetRecordsFilterInfo,
  ): Promise<TaskSnapshot[]> => {
    if (limit <= 0) return [];

    const collected = [...seed];
    const seen = new Set(collected.map((item) => item.recordId));
    const [table, fieldMap] = await Promise.all([getCachedTable(tableId), getCachedFieldMap(tableId)]);

    let pageToken: number | undefined;
    let hasMore = true;

    while (hasMore && collected.length < limit) {
      const response = await table.getRecordsByPage({
        pageSize: 100,
        ...(pageToken ? { pageToken } : {}),
        ...(filter ? { filter } : {}),
      });
      for (const record of response.records) {
        const mapped = mapRecordFields(record, fieldMap);
        if (seen.has(mapped.recordId)) continue;
        if (!predicate(mapped)) continue;
        collected.push(mapped);
        seen.add(mapped.recordId);
        if (collected.length >= limit) break;
      }
      hasMore = response.hasMore;
      pageToken = response.pageToken;
    }

    return collected;
  }, [getCachedFieldMap, getCachedTable]);

  const buildExactTextFilter = useCallback(async (tableId: string, fieldName: string, value: string): Promise<IGetRecordsFilterInfo | null> => {
    const normalizedValue = value.trim();
    if (!normalizedValue) return null;
    const fieldMap = await getCachedFieldMap(tableId);
    const fieldId = getFieldIdByName(fieldMap, fieldName);
    if (!fieldId) return null;
    return {
      conjunction: FilterConjunction.And,
      conditions: [
        {
          fieldId,
          operator: FilterOperator.Is,
          value: normalizedValue,
        },
      ],
    };
  }, [getCachedFieldMap]);

  useEffect(() => {
    let mounted = true;

    async function bootstrap() {
      try {
        const [taskId, reviewId, actionId, archiveId] = await Promise.all([
          resolveTableIdByName(TASK_TABLE_NAME),
          resolveTableIdByName(REVIEW_TABLE_NAME),
          resolveTableIdByName(ACTION_TABLE_NAME),
          resolveTableIdByName(ARCHIVE_TABLE_NAME),
        ]);
        if (!mounted) return;
        setTableIds({ task: taskId, review: reviewId, action: actionId, archive: archiveId });
        setSelection(await bitable.base.getSelection());
        const off = bitable.base.onSelectionChange(({ data }) => setSelection(data));
        return off;
      } catch (err) {
        if (!mounted) return null;
        setError(`插件初始化失败：${String(err)}`);
        setLoading(false);
        return null;
      }
    }

    const offPromise: Promise<(() => void) | null> | null = bootstrap();
    return () => {
      mounted = false;
      offPromise?.then((off) => off?.());
      unsubscribeRef.current?.();
    };
  }, []);

  useEffect(() => {
    const nextSourceKind = getWorkflowSourceKind(selection.tableId, tableIds);
    setSourceKind(nextSourceKind);

    if (!tableIds.task || !selection.recordId) {
      setTask(null);
      setReview(null);
      setActions([]);
      setArchives([]);
      setLive(null);
      setResolutionDebug(null);
      setSelectedRecordSnapshot(null);
      setLoading(false);
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      return;
    }

    if (nextSourceKind === "unsupported") {
      setTask(null);
      setReview(null);
      setActions([]);
      setArchives([]);
      setLive(null);
      setResolutionDebug(null);
      setSelectedRecordSnapshot(null);
      setLoading(false);
      unsubscribeRef.current?.();
      unsubscribeRef.current = null;
      return;
    }

    let active = true;
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;

    async function load() {
      setLoading(true);
      setError("");
      try {
        const selectedRecord = await getMappedRecordById(selection.tableId!, selection.recordId!);
        setSelectedRecordSnapshot(selectedRecord);
        const locator = buildTaskLocator(nextSourceKind, selectedRecord, selection.recordId);

        let currentTask: TaskSnapshot | null = nextSourceKind === "task" ? selectedRecord : null;
        if (!currentTask && locator.taskRecordId) {
          try {
            currentTask = await getMappedRecordById(tableIds.task, locator.taskRecordId);
          } catch {
            currentTask = null;
          }
        }
        if (!currentTask && locator.taskTitle) {
          const taskTitleFilter = await buildExactTextFilter(tableIds.task, "任务标题", locator.taskTitle);
          currentTask = (await collectMappedRecords(tableIds.task, (item) => matchesTaskRecord(item, locator), 1, [], taskTitleFilter || undefined))[0] || null;
        }
        if (!active) return;

        const stableLocator = buildTaskLocator(nextSourceKind, currentTask ?? selectedRecord, selection.recordId);
        const seededReview = nextSourceKind === "review" && matchesRelatedRecord(selectedRecord, stableLocator) ? [selectedRecord] : [];
        const seededActions = nextSourceKind === "action" && matchesRelatedRecord(selectedRecord, stableLocator) ? [selectedRecord] : [];
        const seededArchives = nextSourceKind === "archive" && matchesRelatedRecord(selectedRecord, stableLocator) ? [selectedRecord] : [];
        const recordIdFilter = stableLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.review, "关联记录ID", stableLocator.taskRecordId)
          : null;
        const actionRecordIdFilter = stableLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.action, "关联记录ID", stableLocator.taskRecordId)
          : null;
        const archiveRecordIdFilter = stableLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.archive, "关联记录ID", stableLocator.taskRecordId)
          : null;
        const reviewTitleFilter = !recordIdFilter && stableLocator.taskTitle
          ? await buildExactTextFilter(tableIds.review, "任务标题", stableLocator.taskTitle)
          : null;
        const actionTitleFilter = !actionRecordIdFilter && stableLocator.taskTitle
          ? await buildExactTextFilter(tableIds.action, "任务标题", stableLocator.taskTitle)
          : null;
        const archiveTitleFilter = !archiveRecordIdFilter && stableLocator.taskTitle
          ? await buildExactTextFilter(tableIds.archive, "任务标题", stableLocator.taskTitle)
          : null;

        const [reviewMatches, actionMatches, archiveMatches] = await Promise.all([
          collectMappedRecords(tableIds.review, (item) => matchesRelatedRecord(item, stableLocator), 1, seededReview, recordIdFilter || reviewTitleFilter || undefined),
          collectMappedRecords(tableIds.action, (item) => matchesRelatedRecord(item, stableLocator), 6, seededActions, actionRecordIdFilter || actionTitleFilter || undefined),
          collectMappedRecords(tableIds.archive, (item) => matchesRelatedRecord(item, stableLocator), 3, seededArchives, archiveRecordIdFilter || archiveTitleFilter || undefined),
        ]);
        if (!active) return;

        const currentReview = reviewMatches[0] || null;
        const currentActions = actionMatches.slice(0, 6);
        const currentArchives = archiveMatches.slice(0, 3);

        setTask(currentTask);
        setReview(currentReview);
        setActions(currentActions);
        setArchives(currentArchives);
        setResolutionDebug(buildResolutionDebug(nextSourceKind, selectedRecord, stableLocator, currentTask));

        if (currentTask?.recordId && getRuntimeApiKey()) {
          unsubscribeRef.current = subscribeTaskProgress(currentTask.recordId, (event: ProgressEvent) => {
            setLive((prev) => {
              const nextStep = buildLiveStepEvent(event);
              const nextHistory = nextStep ? [...(prev?.history || []), nextStep].slice(-10) : prev?.history || [];
              return {
                stage: String(event.payload.stage || prev?.stage || "等待调度"),
                progress: safeProgress(event.payload.progress ?? prev?.progress ?? 0),
                status:
                  event.event_type === "task.done"
                    ? "done"
                    : event.event_type === "task.error"
                      ? "error"
                      : prev?.status || "running",
                updatedAt: event.ts,
                tokenPreview:
                  event.event_type === "agent.token"
                    ? textValue(event.payload.chunk) || prev?.tokenPreview
                    : prev?.tokenPreview,
                activeAgent:
                  event.event_type === "agent.token"
                    ? textValue(event.payload.agent_name || event.payload.agent_id) || prev?.activeAgent
                    : prev?.activeAgent,
                history: nextHistory,
                workflowSteps: event.payload.workflow_steps
                  ? normalizeWorkflowSteps(event.payload.workflow_steps)
                  : prev?.workflowSteps,
              };
            });
          });
        } else {
          setLive(null);
        }
      } catch (err) {
        if (!active) return;
        setError(`加载多维表格记录失败：${String(err)}`);
        setResolutionDebug(null);
        setSelectedRecordSnapshot(null);
      } finally {
        if (active) setLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
    };
  }, [buildExactTextFilter, collectMappedRecords, getMappedRecordById, selection, tableIds]);

  const workflowSteps = useMemo(
    () => buildWorkflowDetails(task, review, actions, archives, live),
    [actions, archives, live, review, task],
  );

  const activeStep = useMemo(
    () => workflowSteps.find((step) => step.status === "running") || workflowSteps.find((step) => step.status === "error") || workflowSteps[0] || null,
    [workflowSteps],
  );

  const title = textValue(task?.fields["任务标题"]);
  const status = textValue(task?.fields["状态"]) || "待分析";
  const progress = live ? Math.max(safeProgress(task?.fields["进度"]), live.progress) : safeProgress(task?.fields["进度"]);
  const reviewAction = textValue(task?.fields["最新评审动作"]) || textValue(review?.fields["推荐动作"]) || "待评审";
  const sourceLabel = workflowSourceLabel(sourceKind);
  const selectedRecordTitle = textValue(selectedRecordSnapshot?.fields["任务标题"]);
  const sourceContextItems = useMemo<WorkflowSummaryItem[]>(
    () => buildSourceContextItems(sourceKind, selectedRecordSnapshot),
    [selectedRecordSnapshot, sourceKind],
  );
  const relationSummaryItems = useMemo<WorkflowSummaryItem[]>(
    () => [
      { label: "评审命中", value: review ? "1 条" : "0 条" },
      { label: "动作命中", value: `${actions.length} 条` },
      { label: "归档命中", value: `${archives.length} 条` },
    ],
    [actions.length, archives.length, review],
  );
  const relationSections = useMemo<WorkflowRelationSection[]>(
    () => buildRelationSections(review, actions, archives),
    [actions, archives, review],
  );
  const taskSignalItems = useMemo<WorkflowSummaryItem[]>(
    () => [
      { label: "目标对象", value: textValue(task?.fields["目标对象"]) || "未指定" },
      { label: "当前阶段", value: live?.stage || textValue(task?.fields["当前阶段"]) || "等待调度" },
      { label: "工作流路由", value: textValue(task?.fields["工作流路由"]) || "待生成" },
      { label: "当前责任", value: textValue(task?.fields["当前责任角色"]) || "系统调度" },
    ],
    [live?.stage, task],
  );
  const evidenceItems = useMemo<WorkflowSummaryItem[]>(
    () => [
      { label: "证据条数", value: `${numberValue(task?.fields["证据条数"])} 条` },
      { label: "高置信证据", value: `${numberValue(task?.fields["高置信证据数"])} 条` },
      { label: "硬证据", value: `${numberValue(task?.fields["硬证据数"])} 条` },
      { label: "需补数条数", value: `${numberValue(task?.fields["需补数条数"])} 条` },
    ],
    [task],
  );

  const renderResolutionCard = () =>
    resolutionDebug ? (
      <div className="rounded-[24px] border border-slate-200 bg-white/92 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Traceability</div>
            <div className="mt-2 text-lg font-semibold text-slate-950">回溯诊断</div>
          </div>
          <div className={`rounded-full border px-3 py-1 text-[11px] font-medium ${RESOLUTION_STYLE[resolutionDebug.resolutionMode]}`}>
            {resolutionDebug.resolutionLabel}
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {[
            `来源表：${resolutionDebug.sourceLabel}`,
            `当前记录ID：${resolutionDebug.selectedRecordId || "缺失"}`,
            `关联记录ID：${resolutionDebug.taskRecordIdCandidate || "缺失"}`,
            `任务标题：${resolutionDebug.taskTitleCandidate || "缺失"}`,
          ].map((item) => (
            <div key={item} className="rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-2 text-sm leading-6 text-slate-600">
              {item}
            </div>
          ))}
        </div>
        {!!resolutionDebug.issues.length && (
          <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/80 px-3 py-3 text-sm leading-6 text-rose-700">
            {resolutionDebug.issues.join("；")}
          </div>
        )}
      </div>
    ) : null;

  const renderEntryContextCard = () =>
    selectedRecordSnapshot ? (
      <div className="rounded-[24px] border border-slate-200 bg-white/92 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Entry Context</div>
            <div className="mt-2 text-lg font-semibold text-slate-950">当前记录上下文</div>
          </div>
          <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600">
            {sourceLabel}
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {[...sourceContextItems, ...relationSummaryItems].map((item) => (
            <div key={`${item.label}:${item.value}`} className="rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-2">
              <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">{item.label}</div>
              <div className="mt-1 text-sm leading-6 text-slate-700">{item.value}</div>
            </div>
          ))}
        </div>
      </div>
    ) : null;

  const renderRelationObjectsCard = () => (
    <div className="rounded-[24px] border border-slate-200 bg-white/92 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Related Objects</div>
          <div className="mt-2 text-lg font-semibold text-slate-950">关联对象清单</div>
        </div>
        <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600">
          共 {relationSections.reduce((sum, section) => sum + section.count, 0)} 条
        </div>
      </div>
      <div className="mt-4 space-y-4">
        {relationSections.map((section) => (
          <div key={section.key} className="rounded-[22px] border border-slate-200 bg-slate-50/70 p-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm font-semibold text-slate-900">{section.label}</div>
              <div className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600">
                {section.count} 条
              </div>
            </div>
            {!section.items.length ? (
              <div className="mt-3 text-sm leading-6 text-slate-500">{section.emptyText}</div>
            ) : (
              <div className="mt-3 space-y-3">
                {section.items.map((item) => (
                  <div key={item.key} className="rounded-2xl border border-white/90 bg-white/95 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-slate-950">{item.title}</div>
                        <div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-400">{item.tableLabel}</div>
                      </div>
                      <div className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                        {item.status}
                      </div>
                    </div>
                    <div className="mt-2 text-sm leading-6 text-slate-600">{item.summary}</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <span className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-[11px] font-medium text-sky-700">
                        路由 · {item.route}
                      </span>
                      {item.chips.map((chip) => (
                        <span key={`${item.key}:${chip}`} className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-600">
                          {chip}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,rgba(248,250,252,0.94),rgba(255,255,255,0.98))] p-4 text-slate-900">
      <div className="mx-auto max-w-6xl">
        <div className="rounded-[28px] border border-slate-200 bg-white/92 p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Bitable Embedded Workflow</div>
              <div className="mt-2 text-2xl font-semibold text-slate-950">多维表格内嵌执行面板</div>
              <div className="mt-2 text-sm leading-6 text-slate-600">
                这个版本不走独立 `/workflow` 页面，而是跟随你在工作流相关表里选中的记录直接展示。
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-3 text-sm text-slate-600">
              当前入口：{sourceLabel} · {title || "请先选中一条工作流记录"}
            </div>
          </div>

          {!getRuntimeApiKey() && (
            <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/90 px-4 py-3 text-sm leading-6 text-amber-800">
              当前域名下未检测到 API Key，插件仍可读取多维表格里的任务数据，但不会订阅后端 SSE 实时流。
              需要实时步骤流时，请先在同域站点写入 `localStorage["{API_KEY_STORAGE_KEY}"]`。
            </div>
          )}

          {loading ? (
            <div className="mt-6 flex items-center gap-2 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载多维表格上下文...
            </div>
          ) : error ? (
            <div className="mt-6">
              <EmptyState text={error} />
            </div>
          ) : !selection.recordId || sourceKind === "unsupported" ? (
            <div className="mt-6">
              <EmptyState text="请在「分析任务 / 产出评审 / 交付动作 / 交付结果归档」任一工作流表中选中记录。插件会在右侧面板自动回溯并展示对应任务轨道。" />
            </div>
          ) : !task ? (
            <div className="mt-6 grid gap-6 xl:grid-cols-[1.02fr_0.98fr]">
              <section className="space-y-6">
                <div className="rounded-[28px] border border-slate-200 bg-[linear-gradient(135deg,rgba(251,191,36,0.10),rgba(255,255,255,0.98)_42%,rgba(248,250,252,0.90))] p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="max-w-3xl">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">待人工修正</span>
                        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700">{sourceLabel}</span>
                      </div>
                      <div className="mt-4 text-3xl font-semibold leading-tight text-slate-950">
                        {selectedRecordTitle || "当前记录尚未关联到分析任务"}
                      </div>
                      <div className="mt-3 text-sm leading-7 text-slate-700">
                        你当前选中的不是主任务记录，且插件还没有成功回溯到对应分析任务。请优先检查该行是否具备完整的 `关联记录ID` 或 `任务标题`。
                      </div>
                    </div>
                  </div>
                </div>

                {renderResolutionCard()}
                {renderEntryContextCard()}
                {renderRelationObjectsCard()}
              </section>

              <section className="rounded-[28px] border border-slate-200 bg-white/94 p-5 shadow-sm">
                <EmptyState text={`当前已从「${sourceLabel}」进入，但还没有成功回溯到对应分析任务。请检查该行的「关联记录ID」或「任务标题」是否完整。`} />
              </section>
            </div>
          ) : (
            <div className="mt-6 grid gap-6 xl:grid-cols-[1.02fr_0.98fr]">
              <section className="space-y-6">
                <div className="rounded-[28px] border border-slate-200 bg-[linear-gradient(135deg,rgba(15,118,110,0.08),rgba(255,255,255,0.98)_38%,rgba(14,165,233,0.08))] p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="max-w-3xl">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700">{status}</span>
                        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700">
                          {textValue(task.fields["输出目的"]) || "未标注输出目的"}
                        </span>
                        <span className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700">
                          {reviewAction}
                        </span>
                      </div>
                      <div className="mt-4 text-3xl font-semibold leading-tight text-slate-950">{title}</div>
                      <div className="mt-3 text-sm leading-7 text-slate-700">
                        {textValue(task.fields["最新管理摘要"]) || textValue(task.fields["背景说明"]) || "等待管理摘要生成。"}
                      </div>
                    </div>
                    <div className="w-full max-w-xs rounded-[24px] border border-white/70 bg-white/90 p-4 shadow-sm">
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Task Signals</div>
                      <div className="mt-3 grid gap-3">
                        {taskSignalItems.map((item) => (
                          <div key={item.label} className="rounded-2xl border border-slate-200 bg-white/90 px-3 py-2.5">
                            <div className="text-[11px] uppercase tracking-[0.16em] text-slate-400">{item.label}</div>
                            <div className="mt-1 text-sm leading-6 text-slate-700">{item.value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5">
                    <Progress value={progress} className="h-2.5" />
                    <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                      <span>{live?.stage || textValue(task.fields["当前阶段"]) || "等待调度"}</span>
                      <span>{progress.toFixed(0)}%</span>
                    </div>
                  </div>
                </div>

                {renderResolutionCard()}
                {renderEntryContextCard()}
                {renderRelationObjectsCard()}

                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  {evidenceItems.map((item) => (
                    <div key={item.label} className="rounded-[22px] border border-slate-200 bg-white/92 p-4">
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                      <div className="mt-2 text-lg font-semibold text-slate-950">{item.value}</div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="rounded-[28px] border border-slate-200 bg-white/94 p-5 shadow-sm">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Agent Workflow</div>
                    <div className="mt-2 text-2xl font-semibold text-slate-950">多维表格内执行轨道</div>
                    <div className="mt-2 text-sm leading-6 text-slate-600">
                      这块面板直接嵌在多维表格扩展脚本里，跟随当前选中任务行变化。
                    </div>
                  </div>
                  <div className={`rounded-full px-3 py-1 text-xs font-medium ${live?.status === "done" ? "bg-emerald-100 text-emerald-700" : live?.status === "error" ? "bg-rose-100 text-rose-700" : "bg-sky-100 text-sky-700"}`}>
                    {live?.status === "done" ? "已完成" : live?.status === "error" ? "异常待重试" : "执行中"}
                  </div>
                </div>

                <div className="mt-4 rounded-[24px] border border-slate-200 bg-slate-50/80 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Current Step</div>
                      <div className="mt-2 text-lg font-semibold text-slate-950">{activeStep?.title || "等待进入步骤"}</div>
                    </div>
                    <div className={`rounded-full border px-3 py-1 text-[11px] font-medium ${WORKFLOW_DETAIL_STATUS_STYLE[activeStep?.status || "pending"]}`}>
                      {activeStep?.status === "done" ? "Closed" : activeStep?.status === "error" ? "Error" : activeStep?.status === "running" ? "Live" : "Queued"}
                    </div>
                  </div>
                  <div className="mt-3 text-sm leading-6 text-slate-600">{activeStep?.description || "等待步骤说明"}</div>
                </div>

                {live?.tokenPreview && (
                  <div className="mt-4 rounded-[24px] border border-sky-200 bg-[linear-gradient(135deg,rgba(224,242,254,0.72),rgba(255,255,255,0.96))] p-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-950">
                      <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
                      <span>实时流{live.activeAgent ? ` · ${live.activeAgent}` : ""}</span>
                    </div>
                    <div className="mt-2 text-sm leading-6 text-slate-600">{live.tokenPreview}</div>
                  </div>
                )}

                <div className="mt-5 space-y-4">
                  {workflowSteps.map((step, index) => {
                    const isCurrent = step.key === activeStep?.key;
                    const isError = step.status === "error";
                    const isDone = step.status === "done";
                    return (
                      <div key={step.key} className="relative pl-10">
                        {index < workflowSteps.length - 1 && <div className="absolute left-[15px] top-10 h-[calc(100%+0.5rem)] w-px bg-slate-200" />}
                        <div
                          className={`absolute left-0 top-1 flex h-8 w-8 items-center justify-center rounded-full border ${
                            isError
                              ? "border-rose-200 bg-rose-50 text-rose-600"
                              : isDone
                                ? "border-emerald-200 bg-emerald-50 text-emerald-600"
                                : isCurrent
                                  ? "border-sky-200 bg-sky-50 text-sky-600"
                                  : "border-slate-200 bg-white text-slate-400"
                          }`}
                        >
                          {isError ? (
                            <ShieldAlert className="h-4 w-4" />
                          ) : isDone ? (
                            <CheckCircle2 className="h-4 w-4" />
                          ) : isCurrent ? (
                            <Sparkles className="h-4 w-4 animate-pulse" />
                          ) : (
                            <Clock3 className="h-4 w-4" />
                          )}
                        </div>
                        <div className={`rounded-[22px] border p-4 ${isCurrent ? "border-sky-200 bg-sky-50/80" : "border-slate-200 bg-white/92"}`}>
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <div className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${WORKFLOW_DETAIL_STATUS_STYLE[step.status]}`}>
                                  {step.status === "done" ? "已完成" : step.status === "error" ? "失败" : step.status === "pending" ? "待开始" : "执行中"}
                                </div>
                                <div className="text-sm font-semibold text-slate-950">{step.title}</div>
                              </div>
                              <div className="mt-2 text-sm leading-6 text-slate-700">{step.description}</div>
                            </div>
                            <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">0{index + 1}</div>
                          </div>
                          <div className="mt-3 space-y-2">
                            {step.items.slice(0, isCurrent ? 4 : 2).map((item) => (
                              <div key={item} className="rounded-xl border border-white/80 bg-white/88 px-3 py-2 text-sm leading-6 text-slate-600">
                                {item}
                              </div>
                            ))}
                          </div>
                          {step.note && (
                            <div className="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50/90 px-3 py-2 text-sm leading-6 text-slate-500">
                              {step.note}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-5 rounded-[24px] border border-slate-200 bg-white/92 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Live Timeline</div>
                      <div className="mt-2 text-lg font-semibold text-slate-950">阶段时间线</div>
                    </div>
                    <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                      最近 {live?.history.length || 0} 条
                    </div>
                  </div>
                  {!live?.history.length ? (
                    <div className="mt-4 text-sm leading-6 text-slate-500">如果当前任务正在分析中，这里会跟着展示 wave 和交付事件。</div>
                  ) : (
                    <div className="mt-4 space-y-3">
                      {live.history.slice(-6).reverse().map((event) => (
                        <div key={event.key} className="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-medium text-slate-950">{event.stage}</div>
                            <div className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${STEP_STATUS_STYLE[event.status]}`}>
                              {event.status === "done" ? "完成" : event.status === "error" ? "异常" : "推进"}
                            </div>
                          </div>
                          <div className="mt-2 text-sm leading-6 text-slate-600">{event.detail}</div>
                          <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                            <span>{formatRelativeTime(event.updatedAt)}</span>
                            <span>{formatDateValue(event.updatedAt)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            </div>
          )}

          <div className="mt-6 flex flex-wrap gap-3">
            <Button
              variant="outline"
              onClick={() => {
                setLoading(true);
                void bitable.base.getSelection().then((next) => setSelection(next));
              }}
            >
              <Activity className="mr-2 h-4 w-4" />
              刷新当前选中
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
