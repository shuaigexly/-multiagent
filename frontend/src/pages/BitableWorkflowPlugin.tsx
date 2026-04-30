import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FilterConjunction, FilterOperator, bitable, type IGetRecordsFilterInfo } from "@lark-base-open/js-sdk";
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  Clock3,
  GitBranch,
  Loader2,
  Radio,
  ShieldAlert,
  Sparkles,
  TimerReset,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { AGENT_PERSONAS } from "@/components/agentPersonas";
import { API_KEY_STORAGE_KEY, getRuntimeApiKey } from "@/services/http";
import { subscribeTaskProgress, type AgentPipelineSnapshot, type ProgressEvent, type WorkflowStreamStatus } from "@/services/workflow";
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
  workflowSourceLabel,
  type WorkflowResolutionDebug,
  type WorkflowRelationSection,
  type WorkflowSummaryItem,
  type WorkflowSourceKind,
} from "./bitableWorkflowPluginUtils";
import {
  EmptyState,
  EntryContextCard,
  RelationObjectsCard,
  ResolutionCard,
  TraceChainCard,
} from "./bitableWorkflowPluginCards";
import BitableAgentLauncher from "./BitableAgentLauncher";

type StepStatus = "done" | "running" | "pending" | "error";
type TimelineFilter = "all" | "base" | "sse" | "error";
type HealthTone = "success" | "running" | "warning" | "error" | "neutral";
type WorkspaceMode = "run" | "context" | "delivery";

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
  eventType: ProgressEvent["event_type"] | "native.log";
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
  streamStatus?: WorkflowStreamStatus;
  streamMessage?: string;
  tokenPreview?: string;
  activeAgent?: string;
  history: LiveStepEvent[];
  workflowSteps?: WorkflowStepDetail[];
  agentPipeline?: AgentPipelineSnapshot[];
}

interface BitableRecordValue {
  recordId?: string;
  fields: Record<string, unknown>;
}

interface BitableTableLike {
  getRecordById(recordId: string): Promise<BitableRecordValue>;
  getRecordsByPage(params: { pageSize?: number; pageToken?: string; filter?: IGetRecordsFilterInfo }): Promise<{
    records: BitableRecordValue[];
    hasMore: boolean;
    pageToken?: string;
  }>;
}

interface RuntimeHealthItem {
  key: string;
  label: string;
  value: string;
  caption: string;
  tone: HealthTone;
  icon: LucideIcon;
}

const TASK_TABLE_NAME = "分析任务";
const REVIEW_TABLE_NAME = "产出评审";
const ACTION_TABLE_NAME = "交付动作";
const ARCHIVE_TABLE_NAME = "交付结果归档";
const AUTOMATION_LOG_TABLE_NAME = "自动化日志";
const RELATION_SCAN_PAGE_SIZE = 80;
const RELATION_SCAN_MAX_PAGES = 6;

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

const STREAM_STATUS_STYLE: Record<WorkflowStreamStatus, string> = {
  connecting: "border-amber-200 bg-amber-50 text-amber-700",
  connected: "border-emerald-200 bg-emerald-50 text-emerald-700",
  closed: "border-slate-200 bg-slate-100 text-slate-600",
  error: "border-rose-200 bg-rose-50 text-rose-700",
};

const STREAM_STATUS_LABEL: Record<WorkflowStreamStatus, string> = {
  connecting: "连接中",
  connected: "实时在线",
  closed: "已关闭",
  error: "Base 回退",
};

const TIMELINE_FILTER_LABEL: Record<TimelineFilter, string> = {
  all: "全部",
  base: "Base",
  sse: "SSE",
  error: "异常",
};
const TIMELINE_FILTERS: TimelineFilter[] = ["all", "base", "sse", "error"];
const WORKSPACE_MODE_LABEL: Record<WorkspaceMode, string> = {
  run: "运行",
  context: "上下文",
  delivery: "交付",
};
const WORKSPACE_MODES: WorkspaceMode[] = ["run", "context", "delivery"];

const AGENT_NODE_STYLE: Record<AgentPipelineSnapshot["status"], string> = {
  running: "border-sky-300 bg-sky-50 text-sky-700 shadow-[0_0_0_4px_rgba(14,165,233,0.10)]",
  done: "border-emerald-200 bg-emerald-50 text-emerald-700",
  pending: "border-slate-200 bg-white text-slate-500",
  error: "border-rose-200 bg-rose-50 text-rose-700 shadow-[0_0_0_4px_rgba(244,63,94,0.10)]",
};

const AGENT_STATUS_LABEL: Record<AgentPipelineSnapshot["status"], string> = {
  running: "运行中",
  done: "已完成",
  pending: "待接力",
  error: "异常",
};

const RESOLUTION_STYLE: Record<WorkflowResolutionDebug["resolutionMode"], string> = {
  "selected-task-record": "border-emerald-200 bg-emerald-50 text-emerald-700",
  "related-record-id": "border-sky-200 bg-sky-50 text-sky-700",
  "task-title-fallback": "border-amber-200 bg-amber-50 text-amber-700",
  unresolved: "border-rose-200 bg-rose-50 text-rose-700",
};

const HEALTH_TONE_STYLE: Record<HealthTone, string> = {
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  running: "border-sky-200 bg-sky-50 text-sky-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
  error: "border-rose-200 bg-rose-50 text-rose-700",
  neutral: "border-slate-200 bg-slate-50 text-slate-600",
};

const TOKEN_PREVIEW_MAX_CHARS = 900;

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
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return "刚刚更新";
  const diff = Date.now() - timestamp;
  const minutes = Math.max(0, Math.round(diff / 60000));
  if (minutes < 1) return "刚刚更新";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}

function timestampValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    const ms = value < 1_000_000_000_000 ? value * 1000 : value;
    return new Date(ms).toISOString();
  }
  const raw = textValue(value);
  if (!raw) return "";
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? new Date(parsed).toISOString() : raw;
}

function formatDateValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(value < 1_000_000_000_000 ? value * 1000 : value));
  }
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

function appendTokenPreview(current: string | undefined, chunk: string): string {
  const next = `${current || ""}${chunk}`;
  if (next.length <= TOKEN_PREVIEW_MAX_CHARS) return next;
  return `...${next.slice(next.length - TOKEN_PREVIEW_MAX_CHARS)}`;
}

function buildLiveStepEvent(event: ProgressEvent): LiveStepEvent | null {
  if (event.event_type === "agent.token") return null;
  if (event.event_type.startsWith("agent.")) {
    const agentName = textValue(event.payload.agent_name || event.payload.agent_id) || "AI 岗位";
    const wave = textValue(event.payload.wave);
    const durationMs = numberValue(event.payload.duration_ms);
    const status =
      event.event_type === "agent.completed"
        ? "done"
        : event.event_type === "agent.failed"
          ? "error"
          : "running";
    const detail =
      event.event_type === "agent.started"
        ? `${agentName} 已进入分析队列`
        : event.event_type === "agent.completed"
          ? `${agentName} 输出完成${durationMs ? ` · ${(durationMs / 1000).toFixed(1)}s` : ""}`
          : textValue(event.payload.reason) || `${agentName} 分析异常`;
    return {
      key: `${event.event_type}-${textValue(event.payload.agent_id)}-${event.ts}`,
      eventType: event.event_type,
      stage: `${wave ? `${wave} · ` : ""}${agentName}`,
      status,
      updatedAt: event.ts,
      detail,
    };
  }
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

function buildAutomationLogEvent(record: TaskSnapshot): LiveStepEvent | null {
  const statusText = textValue(record.fields["执行状态"]);
  const nodeName = textValue(record.fields["节点名称"]) || textValue(record.fields["日志标题"]);
  if (!nodeName && !statusText) return null;
  const trigger = textValue(record.fields["触发来源"]);
  const summary = textValue(record.fields["日志摘要"]);
  const detail = textValue(record.fields["详细结果"]);
  const timestamp = timestampValue(record.fields["生成时间"]) || new Date().toISOString();
  const status =
    statusText.includes("失败") || statusText.includes("异常")
      ? "error"
      : statusText.includes("已完成") || statusText.includes("已跳过")
        ? "done"
        : "running";
  return {
    key: `native-log-${record.recordId}`,
    eventType: "native.log",
    stage: nodeName || "自动化日志",
    status,
    updatedAt: timestamp,
    detail: summary || detail || trigger || statusText || "已写入原生 workflow 日志",
  };
}

function mergeTimelineEvents(liveHistory: LiveStepEvent[] | undefined, nativeLogs: TaskSnapshot[]): LiveStepEvent[] {
  const items = [
    ...(liveHistory || []),
    ...nativeLogs.map(buildAutomationLogEvent).filter((item): item is LiveStepEvent => Boolean(item)),
  ];
  const seen = new Set<string>();
  return items
    .filter((item) => {
      const signature = `${item.stage}-${item.status}-${item.detail}-${item.updatedAt.slice(0, 16)}`;
      if (seen.has(signature)) return false;
      seen.add(signature);
      return true;
    })
    .sort((a, b) => {
      const left = new Date(a.updatedAt).getTime();
      const right = new Date(b.updatedAt).getTime();
      return (Number.isFinite(right) ? right : 0) - (Number.isFinite(left) ? left : 0);
    })
    .slice(0, 12);
}

function filterTimelineEvents(events: LiveStepEvent[], filter: TimelineFilter): LiveStepEvent[] {
  if (filter === "base") return events.filter((event) => event.eventType === "native.log");
  if (filter === "sse") return events.filter((event) => event.eventType !== "native.log");
  if (filter === "error") return events.filter((event) => event.status === "error");
  return events;
}

function countTimelineEvents(events: LiveStepEvent[]): Record<TimelineFilter, number> {
  return {
    all: events.length,
    base: events.filter((event) => event.eventType === "native.log").length,
    sse: events.filter((event) => event.eventType !== "native.log").length,
    error: events.filter((event) => event.status === "error").length,
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

const AGENT_FLOW_BLUEPRINT: Array<Pick<AgentPipelineSnapshot, "key" | "wave" | "dependency" | "summary">> = [
  { key: "data_analyst", wave: "Wave 1", dependency: "无上游依赖", summary: "指标、趋势、异常和数据可信度" },
  { key: "content_manager", wave: "Wave 1", dependency: "无上游依赖", summary: "内容资产、表达策略和传播角度" },
  { key: "seo_advisor", wave: "Wave 1", dependency: "无上游依赖", summary: "关键词机会、流量入口和实验方向" },
  { key: "product_manager", wave: "Wave 1", dependency: "无上游依赖", summary: "用户痛点、功能机会和路线优先级" },
  { key: "operations_manager", wave: "Wave 1", dependency: "无上游依赖", summary: "执行拆解、资源协调和落地节奏" },
  { key: "finance_advisor", wave: "Wave 2", dependency: "依赖数据分析师输出", summary: "现金流、成本收益和财务风险" },
  { key: "ceo_assistant", wave: "Wave 3", dependency: "汇总全部上游结论", summary: "管理摘要、决策建议和行动优先级" },
];

function makeAgentSnapshot(
  item: Pick<AgentPipelineSnapshot, "key" | "wave" | "dependency" | "summary">,
  status: AgentPipelineSnapshot["status"],
): AgentPipelineSnapshot {
  const persona = AGENT_PERSONAS[item.key];
  return {
    ...item,
    name: persona?.name || item.key,
    role: persona?.title || "AI 岗位",
    status,
  };
}

function mergeAgentRuntimeDetails(target: AgentPipelineSnapshot, source: AgentPipelineSnapshot): AgentPipelineSnapshot {
  return {
    ...target,
    summary: source.summary || target.summary,
    duration_ms: source.duration_ms ?? target.duration_ms,
    confidence: source.confidence ?? target.confidence,
    fallback: source.fallback ?? target.fallback,
    failed: source.failed ?? target.failed,
    reason: source.reason || target.reason,
    evidence_count: source.evidence_count ?? target.evidence_count,
    action_count: source.action_count ?? target.action_count,
  };
}

function waveStatus(
  wave: AgentPipelineSnapshot["wave"],
  progress: number,
  taskStatus: string,
  liveStatus?: LiveState["status"],
): AgentPipelineSnapshot["status"] {
  const text = `${taskStatus} ${liveStatus || ""}`.toLowerCase();
  const failed = liveStatus === "error" || text.includes("失败") || text.includes("error");
  const done = liveStatus === "done" || progress >= 100 || text.includes("已完成") || text.includes("done");
  if (done) return "done";
  if (failed) {
    if (progress >= 75) return wave === "Wave 3" ? "error" : "done";
    if (progress >= 45) return wave === "Wave 1" ? "done" : wave === "Wave 2" ? "error" : "pending";
    return wave === "Wave 1" ? "error" : "pending";
  }
  if (wave === "Wave 1") return progress >= 45 ? "done" : progress > 0 ? "running" : "pending";
  if (wave === "Wave 2") return progress >= 75 ? "done" : progress >= 45 ? "running" : "pending";
  return progress >= 95 ? "done" : progress >= 75 ? "running" : "pending";
}

function normalizeAgentPipeline(
  pipeline: AgentPipelineSnapshot[] | undefined,
  progress: number,
  taskStatus: string,
  liveStatus?: LiveState["status"],
): AgentPipelineSnapshot[] {
  if (pipeline?.length) {
    return AGENT_FLOW_BLUEPRINT.map((fallback) => {
      const current = pipeline.find((item) => item.key === fallback.key);
      if (!current) return makeAgentSnapshot(fallback, waveStatus(fallback.wave, progress, taskStatus, liveStatus));
      const persona = AGENT_PERSONAS[current.key];
      return mergeAgentRuntimeDetails({
        key: current.key,
        name: current.name || persona?.name || current.key,
        role: current.role || persona?.title || "AI 岗位",
        wave: current.wave || fallback.wave,
        dependency: current.dependency || fallback.dependency,
        summary: current.summary || fallback.summary,
        status: ["done", "running", "pending", "error"].includes(current.status)
          ? current.status
          : waveStatus(current.wave || fallback.wave, progress, taskStatus, liveStatus),
      }, current);
    });
  }
  return AGENT_FLOW_BLUEPRINT.map((item) => makeAgentSnapshot(item, waveStatus(item.wave, progress, taskStatus, liveStatus)));
}

function formatDurationMs(value: number | null | undefined): string {
  if (!value || !Number.isFinite(value)) return "-";
  if (value < 1000) return `${Math.max(1, Math.round(value))}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

function buildRuntimeHealthItems({
  sourceLabel,
  resolutionDebug,
  streamStatus,
  streamMessage,
  automationLogCount,
  agents,
  activeStep,
}: {
  sourceLabel: string;
  resolutionDebug: WorkflowResolutionDebug | null;
  streamStatus?: WorkflowStreamStatus;
  streamMessage?: string;
  automationLogCount: number;
  agents: AgentPipelineSnapshot[];
  activeStep: WorkflowStepDetail | null;
}): RuntimeHealthItem[] {
  const errorAgents = agents.filter((agent) => agent.status === "error").length;
  const runningAgents = agents.filter((agent) => agent.status === "running").length;
  const doneAgents = agents.filter((agent) => agent.status === "done").length;
  const sourceTone: HealthTone =
    resolutionDebug?.resolutionMode === "unresolved"
      ? "error"
      : resolutionDebug?.issues.length
        ? "warning"
        : "success";
  const streamTone: HealthTone =
    streamStatus === "connected"
      ? "success"
      : streamStatus === "connecting"
        ? "running"
        : streamStatus === "error"
          ? "warning"
          : streamStatus === "closed"
            ? "neutral"
            : "warning";
  const agentTone: HealthTone =
    errorAgents > 0
      ? "error"
      : runningAgents > 0
        ? "running"
        : doneAgents >= agents.length
          ? "success"
          : "neutral";

  return [
    {
      key: "source",
      label: "来源绑定",
      value: sourceLabel,
      caption: resolutionDebug?.resolutionLabel || "等待记录定位",
      tone: sourceTone,
      icon: GitBranch,
    },
    {
      key: "stream",
      label: "实时流",
      value: streamStatus ? STREAM_STATUS_LABEL[streamStatus] : "仅 Base",
      caption: streamMessage || "以多维表格沉淀状态为准",
      tone: streamTone,
      icon: Radio,
    },
    {
      key: "logs",
      label: "原生日志",
      value: `${automationLogCount} 条`,
      caption: automationLogCount > 0 ? "自动化日志表已沉淀事件" : "等待 workflow 节点写入",
      tone: automationLogCount > 0 ? "success" : "warning",
      icon: Activity,
    },
    {
      key: "agents",
      label: "Agent 状态",
      value: errorAgents > 0 ? `${errorAgents} 异常` : runningAgents > 0 ? `${runningAgents} 运行中` : `${doneAgents}/${agents.length} 完成`,
      caption: activeStep?.title || "等待调度",
      tone: agentTone,
      icon: BrainCircuit,
    },
  ];
}

function WorkflowCommandBar({
  title,
  sourceLabel,
  status,
  progress,
  stage,
  route,
  reviewAction,
  streamStatus,
  healthItems,
  workspaceMode,
  onWorkspaceModeChange,
}: {
  title: string;
  sourceLabel: string;
  status: string;
  progress: number;
  stage: string;
  route: string;
  reviewAction: string;
  streamStatus?: WorkflowStreamStatus;
  healthItems: RuntimeHealthItem[];
  workspaceMode: WorkspaceMode;
  onWorkspaceModeChange: (mode: WorkspaceMode) => void;
}) {
  const statusClass =
    status.includes("完成")
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status.includes("失败") || status.includes("异常")
        ? "border-rose-200 bg-rose-50 text-rose-700"
        : "border-sky-200 bg-sky-50 text-sky-700";
  const signals = [
    { label: "入口", value: sourceLabel, icon: Activity },
    { label: "路由", value: route || "待生成", icon: GitBranch },
    { label: "评审", value: reviewAction || "待评审", icon: Zap },
    { label: "阶段", value: stage || "等待调度", icon: Radio },
  ];
  const primarySignals = signals.slice(1);

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_8px_22px_rgba(15,23,42,0.06)]">
      <div className="p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white">
                <GitBranch className="h-3.5 w-3.5" />
              </span>
              <span className="truncate">Workflow console</span>
            </div>
            <div className="mt-1 line-clamp-2 text-lg font-semibold leading-snug text-slate-950">
              {title || "未命名任务"}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <span className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${statusClass}`}>{status}</span>
            {streamStatus && (
              <span className={`rounded-md border px-2 py-1 text-[11px] font-semibold ${STREAM_STATUS_STYLE[streamStatus]}`}>
                {STREAM_STATUS_LABEL[streamStatus]}
              </span>
            )}
          </div>
        </div>

        <div className="mt-3 overflow-hidden rounded-lg bg-slate-950 p-3 text-white shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[11px] font-medium text-slate-400">当前阶段</div>
              <div className="mt-1 truncate text-sm font-semibold text-white">{stage || "等待调度"}</div>
            </div>
            <div className="shrink-0 text-2xl font-semibold tabular-nums">{progress.toFixed(0)}%</div>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/15">
            <div
              className="h-full rounded-full bg-[linear-gradient(90deg,#38bdf8,#a78bfa,#34d399)] transition-all"
              style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
            />
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-400">
            <span className="min-w-0 truncate">{sourceLabel}</span>
            <span className="shrink-0">{route || "待生成"}</span>
          </div>
        </div>

        <div className="mt-3 flex rounded-lg border border-slate-200 bg-slate-50 p-1">
          {WORKSPACE_MODES.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onWorkspaceModeChange(item)}
              className={`flex-1 rounded-md px-2 py-1.5 text-sm font-medium transition-colors ${
                workspaceMode === item ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-900"
              }`}
            >
              {WORKSPACE_MODE_LABEL[item]}
            </button>
          ))}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          {healthItems.map((item) => (
            <div
              key={item.key}
              title={item.caption}
              className={`min-w-0 rounded-lg border px-2.5 py-2 ${HEALTH_TONE_STYLE[item.tone]}`}
            >
              <div className="flex items-center gap-1.5 text-[10px] font-medium opacity-75">
                <item.icon className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{item.label}</span>
              </div>
              <div className="mt-1 truncate text-sm font-semibold">{item.value}</div>
            </div>
          ))}
        </div>

        <div className="mt-2 grid gap-1.5">
          {primarySignals.map((item) => (
            <div key={item.label} className="flex min-w-0 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white text-slate-600">
                <item.icon className="h-3.5 w-3.5" />
              </span>
              <div className="shrink-0 text-[11px] font-medium text-slate-400">{item.label}</div>
              <div className="min-w-0 truncate text-sm font-medium text-slate-800">{item.value}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CompactAgentFlowPanel({
  agents,
  progress,
  stage,
  route,
  reviewAction,
  evidenceCount,
  pendingDataCount,
  selectedAgentKey,
  selectedAgent,
  timeline,
  streamStatus,
  streamMessage,
  onSelectAgent,
}: {
  agents: AgentPipelineSnapshot[];
  progress: number;
  stage: string;
  route: string;
  reviewAction: string;
  evidenceCount: number;
  pendingDataCount: number;
  selectedAgentKey?: string;
  selectedAgent: AgentPipelineSnapshot | null;
  timeline: LiveStepEvent[];
  streamStatus?: WorkflowStreamStatus;
  streamMessage?: string;
  onSelectAgent?: (agentKey: string) => void;
}) {
  const doneCount = agents.filter((agent) => agent.status === "done").length;
  const runningCount = agents.filter((agent) => agent.status === "running").length;
  const errorCount = agents.filter((agent) => agent.status === "error").length;
  const selectedPersona = selectedAgent ? AGENT_PERSONAS[selectedAgent.key] : null;
  const selectedAgentEvents = selectedAgent
    ? timeline
        .filter((event) => {
          const haystack = `${event.stage} ${event.detail}`;
          return haystack.includes(selectedAgent.name) || haystack.includes(selectedAgent.role) || haystack.includes(selectedAgent.key);
        })
        .slice(0, 2)
    : [];
  const waveOrder = ["Wave 1", "Wave 2", "Wave 3"];
  const waveCaption: Record<string, string> = {
    "Wave 1": "并行分析",
    "Wave 2": "财务校验",
    "Wave 3": "管理汇总",
  };

  return (
    <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_8px_22px_rgba(15,23,42,0.06)]">
      <div className="p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
                <BrainCircuit className="h-3.5 w-3.5" />
              </span>
              <span className="truncate">七岗 AI 流程</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-slate-600">
              <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5">{doneCount}/{agents.length || 7} 完成</span>
              {runningCount > 0 && <span className="rounded-md border border-sky-200 bg-sky-50 px-2 py-0.5 text-sky-700">{runningCount} 运行中</span>}
              {errorCount > 0 && <span className="rounded-md border border-rose-200 bg-rose-50 px-2 py-0.5 text-rose-700">{errorCount} 异常</span>}
            </div>
          </div>
          <div className="shrink-0 rounded-lg bg-slate-950 px-2.5 py-1.5 text-right text-white shadow-sm">
            <div className="text-xl font-semibold tabular-nums">{progress.toFixed(0)}%</div>
            <div className="text-[11px] text-slate-400">{streamStatus ? STREAM_STATUS_LABEL[streamStatus] : "Base"}</div>
          </div>
        </div>

        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,#0ea5e9,#8b5cf6,#10b981)] transition-all"
            style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}
          />
        </div>

        <div className="mt-3 grid grid-cols-2 gap-2">
          {[
            { icon: Radio, label: "阶段", value: stage || "等待调度" },
            { icon: GitBranch, label: "路由", value: route || "待生成" },
            { icon: Zap, label: "评审", value: reviewAction || "待评审" },
            { icon: TimerReset, label: "证据", value: `${evidenceCount} / ${pendingDataCount}` },
          ].map((item) => (
            <div key={item.label} className="min-w-0 rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2">
              <div className="flex items-center gap-1.5 text-[11px] font-medium text-slate-400">
                <item.icon className="h-3.5 w-3.5 shrink-0" />
                <span>{item.label}</span>
              </div>
              <div className="mt-1 truncate text-sm font-medium text-slate-800">{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="border-t border-slate-100 bg-[#fbfcfe] p-3">
        <div className="space-y-3">
          {waveOrder.map((wave) => {
            const waveAgents = agents.filter((agent) => agent.wave === wave);
            if (!waveAgents.length) return null;
            return (
              <div key={wave}>
                <div className="mb-2 flex items-center gap-2">
                  <div className="shrink-0 text-[11px] font-semibold uppercase text-slate-500">{wave}</div>
                  <div className="h-px flex-1 bg-slate-200" />
                  <div className="shrink-0 text-[11px] font-medium text-slate-500">{waveCaption[wave]}</div>
                </div>
                <div className="grid gap-2">
                  {waveAgents.map((agent) => {
                    const persona = AGENT_PERSONAS[agent.key];
                    const isSelected = selectedAgentKey === agent.key;
                    const isRunning = agent.status === "running";
                    const statusDot =
                      agent.status === "done"
                        ? "bg-emerald-500"
                        : agent.status === "error"
                          ? "bg-rose-500"
                          : isRunning
                            ? "bg-sky-500"
                            : "bg-slate-300";
                    return (
                      <button
                        key={agent.key}
                        type="button"
                        onClick={() => onSelectAgent?.(agent.key)}
                        className={`flex w-full min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition-all ${
                          isSelected ? "border-sky-300 bg-white shadow-sm ring-2 ring-sky-100" : "border-slate-200 bg-white/90 hover:border-slate-300 hover:bg-white"
                        }`}
                      >
                        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusDot} ${isRunning ? "animate-pulse" : ""}`} />
                        <div
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-sm font-semibold text-white shadow-sm"
                          style={{ backgroundColor: persona?.color || "#64748b" }}
                        >
                          {persona?.avatar || agent.name.slice(0, 1)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-semibold text-slate-950">{agent.role}</div>
                          <div className="truncate text-xs text-slate-500">{AGENT_STATUS_LABEL[agent.status]} · {agent.dependency}</div>
                        </div>
                        <div className="shrink-0 text-right text-[11px] leading-5 text-slate-500">
                          <div>{formatDurationMs(agent.duration_ms)}</div>
                          <div>{agent.confidence ? `${agent.confidence}/5` : "-"}</div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {selectedAgent && (
        <div className="border-t border-slate-200 bg-white p-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm font-semibold text-white shadow-sm"
              style={{ backgroundColor: selectedPersona?.color || "#64748b" }}
            >
              {selectedPersona?.avatar || selectedAgent.name.slice(0, 1)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <div className="truncate text-sm font-semibold text-slate-950">{selectedAgent.role}</div>
                <span className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${AGENT_NODE_STYLE[selectedAgent.status]}`}>
                  {AGENT_STATUS_LABEL[selectedAgent.status]}
                </span>
              </div>
              <div className="mt-1 line-clamp-3 text-sm leading-6 text-slate-700">
                {selectedAgent.status === "error" ? selectedAgent.reason || selectedAgent.summary : selectedAgent.summary || "等待该岗位输出。"}
              </div>
              {streamMessage && <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{streamMessage}</div>}
            </div>
          </div>

          {!!selectedAgentEvents.length && (
            <div className="mt-3 grid gap-2">
              {selectedAgentEvents.map((event) => (
                <div key={event.key} className="rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 truncate text-sm font-medium text-slate-900">{event.stage}</div>
                    <span className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10px] ${STEP_STATUS_STYLE[event.status]}`}>
                      {event.eventType === "native.log" ? "Base" : "SSE"}
                    </span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{event.detail}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function WorkflowStepRail({
  steps,
  activeStep,
}: {
  steps: WorkflowStepDetail[];
  activeStep: WorkflowStepDetail | null;
}) {
  if (!steps.length) return null;
  const doneCount = steps.filter((step) => step.status === "done").length;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">Workflow Route</div>
          <div className="mt-1 text-base font-semibold text-slate-950">自动化步骤</div>
          <div className="mt-1 line-clamp-1 text-sm text-slate-600">{activeStep?.title || "等待进入步骤"}</div>
        </div>
        <div className="shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-right">
          <div className="text-[10px] font-medium text-slate-400">Closed</div>
          <div className="mt-1 text-sm font-semibold tabular-nums text-slate-900">
            {doneCount}/{steps.length}
          </div>
        </div>
      </div>

      <div className="mt-3 max-h-[360px] space-y-2 overflow-y-auto pr-1">
        {steps.map((step, index) => {
          const isCurrent = step.key === activeStep?.key;
          const isError = step.status === "error";
          const isDone = step.status === "done";
          return (
            <div key={step.key} className="relative pl-8">
              {index < steps.length - 1 && <div className="absolute left-[13px] top-8 h-[calc(100%+0.5rem)] w-px bg-slate-200" />}
              <div
                className={`absolute left-0 top-1 flex h-7 w-7 items-center justify-center rounded-md border ${
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
                  <ShieldAlert className="h-3.5 w-3.5" />
                ) : isDone ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : isCurrent ? (
                  <Sparkles className="h-3.5 w-3.5 animate-pulse" />
                ) : (
                  <Clock3 className="h-3.5 w-3.5" />
                )}
              </div>
              <div className={`rounded-lg border p-2.5 ${isCurrent ? "border-sky-200 bg-sky-50/80" : "border-slate-200 bg-slate-50/70"}`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-center gap-1.5">
                      <div className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${WORKFLOW_DETAIL_STATUS_STYLE[step.status]}`}>
                        {step.status === "done" ? "已完成" : step.status === "error" ? "失败" : step.status === "pending" ? "待开始" : "执行中"}
                      </div>
                      <div className="min-w-0 truncate text-sm font-semibold text-slate-950">{step.title}</div>
                    </div>
                    <div className="mt-1.5 line-clamp-2 text-sm leading-6 text-slate-700">{step.description}</div>
                  </div>
                  <div className="shrink-0 text-[10px] font-medium text-slate-400">0{index + 1}</div>
                </div>
                {!!step.items.length && (
                  <div className="mt-2 grid gap-1.5">
                    {step.items.slice(0, isCurrent ? 4 : 2).map((item) => (
                      <div key={item} className="rounded-md border border-white bg-white/90 px-2.5 py-1.5 text-xs leading-5 text-slate-600">
                        {item}
                      </div>
                    ))}
                  </div>
                )}
                {step.note && (
                  <div className="mt-2 line-clamp-3 rounded-md border border-dashed border-slate-200 bg-white/80 px-2.5 py-1.5 text-xs leading-5 text-slate-500">
                    {step.note}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WorkflowTimelineCard({
  events,
  filteredEvents,
  filter,
  onFilterChange,
  automationLogCount,
  selectedEvent,
  onSelectEvent,
}: {
  events: LiveStepEvent[];
  filteredEvents: LiveStepEvent[];
  filter: TimelineFilter;
  onFilterChange: (filter: TimelineFilter) => void;
  automationLogCount: number;
  selectedEvent: LiveStepEvent | null;
  onSelectEvent: (eventKey: string) => void;
}) {
  const counts = countTimelineEvents(events);
  const selectedIsNative = selectedEvent?.eventType === "native.log";
  const emptyText = events.length
    ? "当前筛选条件下暂无事件。"
    : "任务启动后，这里会优先展示自动化日志表沉淀的 workflow 节点；SSE 在线时会同步补充实时事件。";

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">Workflow Timeline</div>
          <div className="mt-1 text-base font-semibold text-slate-950">阶段时间线</div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-right">
            <div className="text-[10px] font-medium text-slate-400">Base</div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-slate-900">{automationLogCount} 条</div>
          </div>
        </div>
      </div>

      <div className="mt-3 flex overflow-x-auto rounded-lg border border-slate-200 bg-slate-50 p-1">
        {TIMELINE_FILTERS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => onFilterChange(item)}
            className={`shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              filter === item ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-900"
            }`}
          >
            {TIMELINE_FILTER_LABEL[item]} <span className="tabular-nums">{counts[item]}</span>
          </button>
        ))}
      </div>

      {!filteredEvents.length ? (
        <div className="mt-3 rounded-lg border border-dashed border-slate-200 bg-slate-50/80 px-3 py-4 text-sm leading-6 text-slate-500">{emptyText}</div>
      ) : (
        <>
          {selectedEvent && (
            <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/80 p-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${selectedIsNative ? "border-emerald-200 bg-white text-emerald-700" : "border-sky-200 bg-white text-sky-700"}`}>
                      {selectedIsNative ? "Base" : "SSE"}
                    </span>
                    <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${STEP_STATUS_STYLE[selectedEvent.status]}`}>
                      {selectedEvent.status === "done" ? "完成" : selectedEvent.status === "error" ? "异常" : "推进"}
                    </span>
                  </div>
                  <div className="mt-2 text-sm font-semibold text-slate-950">{selectedEvent.stage}</div>
                  <div className="mt-1.5 line-clamp-3 text-sm leading-6 text-slate-700">{selectedEvent.detail}</div>
                </div>
                <div className="shrink-0 text-right text-[11px] leading-5 text-slate-500">
                  <div>{formatRelativeTime(selectedEvent.updatedAt)}</div>
                  <div>{formatDateValue(selectedEvent.updatedAt)}</div>
                </div>
              </div>
            </div>
          )}

          <div className="mt-3 max-h-[320px] space-y-2 overflow-y-auto pr-1">
            {filteredEvents.map((event, index) => {
              const isNative = event.eventType === "native.log";
              const sourceLabel = isNative ? "Base" : "SSE";
              const isSelected = event.key === selectedEvent?.key;
              return (
                <div key={event.key} className="relative pl-6">
                  {index < filteredEvents.length - 1 && <div className="absolute left-[5px] top-5 h-[calc(100%+0.5rem)] w-px bg-slate-200" />}
                  <div
                    className={`absolute left-0 top-3 h-3 w-3 rounded-full border-2 ${
                      event.status === "error"
                        ? "border-rose-500 bg-rose-100"
                        : isNative
                          ? "border-emerald-500 bg-emerald-100"
                          : "border-sky-500 bg-sky-100"
                    }`}
                  />
                  <button
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => onSelectEvent(event.key)}
                    className={`w-full rounded-lg border px-2.5 py-2.5 text-left transition-colors ${
                      isSelected ? "border-sky-300 bg-white shadow-sm" : "border-slate-200 bg-slate-50/80 hover:border-slate-300 hover:bg-white"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-slate-950">{event.stage}</div>
                        <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{event.detail}</div>
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${isNative ? "border-emerald-200 bg-white text-emerald-700" : "border-sky-200 bg-white text-sky-700"}`}>
                          {sourceLabel}
                        </span>
                        <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium ${STEP_STATUS_STYLE[event.status]}`}>
                          {event.status === "done" ? "完成" : event.status === "error" ? "异常" : "推进"}
                        </span>
                      </div>
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-slate-500">
                      <span>{formatRelativeTime(event.updatedAt)}</span>
                      <span>{formatDateValue(event.updatedAt)}</span>
                    </div>
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

async function resolveTableIdByName(name: string): Promise<string> {
  const table = await bitable.base.getTableByName(name);
  return table.id;
}

async function resolveOptionalTableIdByName(name: string): Promise<string> {
  try {
    return await resolveTableIdByName(name);
  } catch {
    return "";
  }
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
  const [automationLogs, setAutomationLogs] = useState<TaskSnapshot[]>([]);
  const [live, setLive] = useState<LiveState | null>(null);
  const [selectedAgentKey, setSelectedAgentKey] = useState("data_analyst");
  const [timelineFilter, setTimelineFilter] = useState<TimelineFilter>("all");
  const [selectedTimelineEventKey, setSelectedTimelineEventKey] = useState("");
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>("run");
  const [resolutionDebug, setResolutionDebug] = useState<WorkflowResolutionDebug | null>(null);
  const [selectedRecordSnapshot, setSelectedRecordSnapshot] = useState<TaskSnapshot | null>(null);
  const unsubscribeRef = useRef<null | (() => void)>(null);
  const tableCacheRef = useRef(new Map<string, Promise<BitableTableLike>>());
  const fieldMapCacheRef = useRef(new Map<string, Promise<Map<string, string>>>());

  const getCachedTable = useCallback((tableId: string) => {
    const cached = tableCacheRef.current.get(tableId);
    if (cached) return cached;
    const promise = bitable.base.getTableById(tableId) as Promise<BitableTableLike>;
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

    let pageToken: string | undefined;
    let hasMore = true;
    let scannedPages = 0;

    while (hasMore && collected.length < limit && scannedPages < RELATION_SCAN_MAX_PAGES) {
      scannedPages += 1;
      const response = await table.getRecordsByPage({
        pageSize: RELATION_SCAN_PAGE_SIZE,
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
      if (hasMore && !pageToken) break;
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
        const [taskId, reviewId, actionId, archiveId, automationLogId] = await Promise.all([
          resolveTableIdByName(TASK_TABLE_NAME),
          resolveTableIdByName(REVIEW_TABLE_NAME),
          resolveTableIdByName(ACTION_TABLE_NAME),
          resolveTableIdByName(ARCHIVE_TABLE_NAME),
          resolveOptionalTableIdByName(AUTOMATION_LOG_TABLE_NAME),
        ]);
        if (!mounted) return;
        setTableIds({
          task: taskId,
          review: reviewId,
          action: actionId,
          archive: archiveId,
          ...(automationLogId ? { automation_log: automationLogId } : {}),
        });
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
      setAutomationLogs([]);
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
      setAutomationLogs([]);
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
      setLive(null);
      setSelectedTimelineEventKey("");
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

        const relationLocator = buildResolvedRelationLocator(locator, currentTask);
        const seededReview = nextSourceKind === "review" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const seededActions = nextSourceKind === "action" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const seededArchives = nextSourceKind === "archive" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const seededLogs = nextSourceKind === "log" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const recordIdFilter = relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.review, "关联记录ID", relationLocator.taskRecordId)
          : null;
        const actionRecordIdFilter = relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.action, "关联记录ID", relationLocator.taskRecordId)
          : null;
        const archiveRecordIdFilter = relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.archive, "关联记录ID", relationLocator.taskRecordId)
          : null;
        const logRecordIdFilter = tableIds.automation_log && relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.automation_log, "关联记录ID", relationLocator.taskRecordId)
          : null;
        const reviewTitleFilter = !recordIdFilter && relationLocator.taskTitle
          ? await buildExactTextFilter(tableIds.review, "任务标题", relationLocator.taskTitle)
          : null;
        const actionTitleFilter = !actionRecordIdFilter && relationLocator.taskTitle
          ? await buildExactTextFilter(tableIds.action, "任务标题", relationLocator.taskTitle)
          : null;
        const archiveTitleFilter = !archiveRecordIdFilter && relationLocator.taskTitle
          ? await buildExactTextFilter(tableIds.archive, "任务标题", relationLocator.taskTitle)
          : null;
        const logTitleFilter = tableIds.automation_log && !logRecordIdFilter && relationLocator.taskTitle
          ? await buildExactTextFilter(tableIds.automation_log, "任务标题", relationLocator.taskTitle)
          : null;

        const [reviewMatches, actionMatches, archiveMatches, logMatches] = await Promise.all([
          collectMappedRecords(tableIds.review, (item) => matchesRelatedRecord(item, relationLocator), 1, seededReview, recordIdFilter || reviewTitleFilter || undefined),
          collectMappedRecords(tableIds.action, (item) => matchesRelatedRecord(item, relationLocator), 6, seededActions, actionRecordIdFilter || actionTitleFilter || undefined),
          collectMappedRecords(tableIds.archive, (item) => matchesRelatedRecord(item, relationLocator), 3, seededArchives, archiveRecordIdFilter || archiveTitleFilter || undefined),
          tableIds.automation_log
            ? collectMappedRecords(tableIds.automation_log, (item) => matchesRelatedRecord(item, relationLocator), 12, seededLogs, logRecordIdFilter || logTitleFilter || undefined)
            : Promise.resolve([]),
        ]);
        if (!active) return;

        const currentReview = reviewMatches[0] || null;
        const currentActions = actionMatches.slice(0, 6);
        const currentArchives = archiveMatches.slice(0, 3);
        const currentLogs = logMatches.slice(0, 12);

        setTask(currentTask);
        setReview(currentReview);
        setActions(currentActions);
        setArchives(currentArchives);
        setAutomationLogs(currentLogs);
        setResolutionDebug(buildResolutionDebug(nextSourceKind, selectedRecord, locator, currentTask));

        if (currentTask?.recordId && getRuntimeApiKey()) {
          const initialProgress = safeProgress(currentTask.fields["进度"]);
          const currentStatusText = textValue(currentTask.fields["状态"]);
          const initialLiveStatus: LiveState["status"] =
            currentStatusText.includes("失败") || currentStatusText.includes("异常")
              ? "error"
              : currentStatusText.includes("完成") || initialProgress >= 100
                ? "done"
                : "running";
          setLive({
            stage: textValue(currentTask.fields["当前阶段"]) || "等待实时流连接",
            progress: initialProgress,
            status: initialLiveStatus,
            updatedAt: new Date().toISOString(),
            streamStatus: "connecting",
            streamMessage: "正在连接后端实时流",
            history: [],
          });
          unsubscribeRef.current = subscribeTaskProgress(
            currentTask.recordId,
            (event: ProgressEvent) => {
              if (!active) return;
              setLive((prev) => {
                const nextStep = buildLiveStepEvent(event);
                const nextHistory = nextStep ? [...(prev?.history || []), nextStep].slice(-10) : prev?.history || [];
                const tokenChunk = event.event_type === "agent.token" ? textValue(event.payload.chunk) : "";
                const nextProgress = event.event_type === "task.done"
                  ? 100
                  : safeProgress(event.payload.progress ?? prev?.progress ?? 0);
                return {
                  stage: String(event.payload.stage || prev?.stage || "等待调度"),
                  progress: nextProgress,
                  status:
                    event.event_type === "task.done"
                      ? "done"
                      : event.event_type === "task.error"
                        ? "error"
                        : prev?.status || "running",
                  updatedAt: event.ts,
                  streamStatus: prev?.streamStatus || "connecting",
                  streamMessage: prev?.streamMessage,
                  tokenPreview: tokenChunk ? appendTokenPreview(prev?.tokenPreview, tokenChunk) : prev?.tokenPreview,
                  activeAgent:
                    event.event_type === "agent.token"
                      ? textValue(event.payload.agent_name || event.payload.agent_id) || prev?.activeAgent
                      : prev?.activeAgent,
                  history: nextHistory,
                  workflowSteps: event.payload.workflow_steps
                    ? normalizeWorkflowSteps(event.payload.workflow_steps)
                    : prev?.workflowSteps,
                  agentPipeline: event.payload.agent_pipeline || prev?.agentPipeline,
                };
              });
            },
            (streamStatus, message) => {
              if (!active) return;
              setLive((prev) => ({
                stage: prev?.stage || textValue(currentTask.fields["当前阶段"]) || "等待调度",
                progress: prev?.progress ?? initialProgress,
                status: prev?.status || "running",
                updatedAt: new Date().toISOString(),
                streamStatus,
                streamMessage: message,
                tokenPreview: prev?.tokenPreview,
                activeAgent: prev?.activeAgent,
                history: prev?.history || [],
                workflowSteps: prev?.workflowSteps,
                agentPipeline: prev?.agentPipeline,
              }));
            },
          );
        } else {
          setLive(null);
        }
      } catch (err) {
        if (!active) return;
        setError(`加载多维表格记录失败：${String(err)}`);
        setResolutionDebug(null);
        setSelectedRecordSnapshot(null);
        setAutomationLogs([]);
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
      { label: "原生日志", value: `${automationLogs.length} 条` },
    ],
    [actions.length, archives.length, automationLogs.length, review],
  );
  const relationSections = useMemo<WorkflowRelationSection[]>(
    () => buildRelationSections(review, actions, archives),
    [actions, archives, review],
  );
  const traceChainItems = useMemo(
    () => buildTraceChainItems(sourceKind, selectedRecordSnapshot, task, review, actions, archives, resolutionDebug, automationLogs),
    [actions, archives, automationLogs, resolutionDebug, review, selectedRecordSnapshot, sourceKind, task],
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
  const agentPipeline = useMemo(
    () => normalizeAgentPipeline(live?.agentPipeline, progress, status, live?.status),
    [live?.agentPipeline, live?.status, progress, status],
  );
  const timelineEvents = useMemo(
    () => mergeTimelineEvents(live?.history, automationLogs),
    [automationLogs, live?.history],
  );
  const filteredTimelineEvents = useMemo(
    () => filterTimelineEvents(timelineEvents, timelineFilter),
    [timelineEvents, timelineFilter],
  );
  const selectedTimelineEvent = useMemo(
    () => filteredTimelineEvents.find((event) => event.key === selectedTimelineEventKey) || filteredTimelineEvents[0] || null,
    [filteredTimelineEvents, selectedTimelineEventKey],
  );
  const selectedAgent = useMemo(
    () =>
      agentPipeline.find((agent) => agent.key === selectedAgentKey) ||
      agentPipeline.find((agent) => agent.status === "running") ||
      agentPipeline.find((agent) => agent.status === "error") ||
      agentPipeline[0] ||
      null,
    [agentPipeline, selectedAgentKey],
  );
  const runtimeHealthItems = useMemo(
    () =>
      buildRuntimeHealthItems({
        sourceLabel,
        resolutionDebug,
        streamStatus: live?.streamStatus,
        streamMessage: live?.streamMessage,
        automationLogCount: automationLogs.length,
        agents: agentPipeline,
        activeStep,
      }),
    [activeStep, agentPipeline, automationLogs.length, live?.streamMessage, live?.streamStatus, resolutionDebug, sourceLabel],
  );

  return (
    <div className="min-h-screen bg-[#f6f8fb] p-2 text-slate-900">
      <div className="mx-auto max-w-[420px] space-y-3">
        {/* v8.6.20-r24：顶部 Agent 启动器 — 直接输入任务一键写入分析任务表 */}
        <BitableAgentLauncher
          onLaunched={(rid) => {
            // 重置选中到新 record，让主面板自动绑定
            setSelection((prev) => ({
              ...prev,
              tableId: tableIds.task || prev.tableId,
              recordId: rid,
            }));
          }}
        />

        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_8px_22px_rgba(15,23,42,0.06)]">
          <div className="h-1 bg-[linear-gradient(90deg,#0ea5e9,#6366f1,#22c55e)]" />
          <div className="p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-950 text-white shadow-sm">
                    <GitBranch className="h-3.5 w-3.5" />
                  </span>
                  <span className="truncate">Bitable Workflow</span>
                </div>
                <div className="mt-1 truncate text-lg font-semibold text-slate-950">AI 运转流程</div>
              </div>
              <div className="min-w-0 shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-right text-xs text-slate-600">
                <div>{sourceLabel}</div>
                <div className="max-w-28 truncate font-medium text-slate-900">{title || "未选中"}</div>
              </div>
            </div>

            {!getRuntimeApiKey() && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/90 px-3 py-2 text-xs leading-5 text-amber-800">
                未检测到 API Key，仅显示 Base 状态。
                <code className="rounded border border-amber-200 bg-white/70 px-1.5 py-0.5">
                  {API_KEY_STORAGE_KEY}
                </code>
              </div>
            )}
          </div>

          {loading ? (
            <div className="mx-3 mb-3 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载多维表格上下文...
            </div>
          ) : error ? (
            <div className="mx-3 mb-3">
              <EmptyState text={error} />
            </div>
          ) : !selection.recordId || sourceKind === "unsupported" ? (
            <div className="mx-3 mb-3">
              <EmptyState text="请选中一条工作流记录。" />
            </div>
          ) : !task ? (
            <div className="mx-3 mb-3 grid gap-3">
              <section className="space-y-3">
                <div className="rounded-lg border border-slate-200 bg-amber-50/70 p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">待修正</span>
                        <span className="rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-700">{sourceLabel}</span>
                      </div>
                      <div className="mt-2 line-clamp-2 text-base font-semibold leading-snug text-slate-950">
                        {selectedRecordTitle || "当前记录尚未关联到分析任务"}
                      </div>
                    </div>
                  </div>
                </div>

                <ResolutionCard resolutionDebug={resolutionDebug} resolutionStyle={RESOLUTION_STYLE} />
                <TraceChainCard nodes={traceChainItems} />
                <EntryContextCard
                  sourceKind={sourceKind}
                  sourceContextItems={sourceContextItems}
                  relationSummaryItems={relationSummaryItems}
                />
                <RelationObjectsCard relationSections={relationSections} />
              </section>
            </div>
          ) : (
            <div className="border-t border-slate-100 bg-[#f8fafc] p-3">
              <WorkflowCommandBar
                title={title}
                sourceLabel={sourceLabel}
                status={status}
                progress={progress}
                stage={live?.stage || textValue(task.fields["当前阶段"]) || "等待调度"}
                route={textValue(task.fields["工作流路由"]) || "待生成"}
                reviewAction={reviewAction}
                streamStatus={live?.streamStatus}
                healthItems={runtimeHealthItems}
                workspaceMode={workspaceMode}
                onWorkspaceModeChange={setWorkspaceMode}
              />

              {workspaceMode === "run" && (
                <section className="mt-3 space-y-3">
                  <CompactAgentFlowPanel
                    agents={agentPipeline}
                    progress={progress}
                    stage={live?.stage || textValue(task.fields["当前阶段"]) || "等待调度"}
                    route={textValue(task.fields["工作流路由"]) || "待生成"}
                    reviewAction={reviewAction}
                    evidenceCount={numberValue(task.fields["证据条数"])}
                    pendingDataCount={numberValue(task.fields["需补数条数"])}
                    selectedAgentKey={selectedAgent?.key}
                    selectedAgent={selectedAgent}
                    timeline={timelineEvents}
                    streamStatus={live?.streamStatus}
                    streamMessage={live?.streamMessage}
                    onSelectAgent={setSelectedAgentKey}
                  />

                  {live?.tokenPreview && (
                    <div className="rounded-lg border border-sky-200 bg-sky-50/70 p-3 shadow-sm">
                      <div className="flex items-center gap-2 text-sm font-medium text-slate-950">
                        <Loader2 className="h-4 w-4 animate-spin text-sky-600" />
                        <span>实时流{live.activeAgent ? ` · ${live.activeAgent}` : ""}</span>
                      </div>
                      <div className="mt-2 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-600">{live.tokenPreview}</div>
                    </div>
                  )}

                  <div className="grid gap-3">
                    <WorkflowStepRail steps={workflowSteps} activeStep={activeStep} />
                    <WorkflowTimelineCard
                      events={timelineEvents}
                      filteredEvents={filteredTimelineEvents}
                      filter={timelineFilter}
                      onFilterChange={setTimelineFilter}
                      automationLogCount={automationLogs.length}
                      selectedEvent={selectedTimelineEvent}
                      onSelectEvent={setSelectedTimelineEventKey}
                    />
                  </div>
                </section>
              )}

              {workspaceMode === "context" && (
                <section className="mt-3 grid gap-3">
                  <div className="space-y-3">
                    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                      <div className="text-xs font-medium text-slate-500">Management Summary</div>
                      <div className="mt-2 text-sm leading-7 text-slate-700">
                        {textValue(task.fields["最新管理摘要"]) || textValue(task.fields["背景说明"]) || "等待管理摘要生成。"}
                      </div>
                      <div className="mt-3 grid gap-2">
                        {taskSignalItems.map((item) => (
                          <div key={item.label} className="rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2">
                            <div className="text-[11px] font-medium text-slate-400">{item.label}</div>
                            <div className="mt-1 line-clamp-2 text-sm font-medium leading-5 text-slate-800">{item.value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <ResolutionCard resolutionDebug={resolutionDebug} resolutionStyle={RESOLUTION_STYLE} />
                    <EntryContextCard
                      sourceKind={sourceKind}
                      sourceContextItems={sourceContextItems}
                      relationSummaryItems={relationSummaryItems}
                    />
                  </div>
                  <TraceChainCard nodes={traceChainItems} />
                </section>
              )}

              {workspaceMode === "delivery" && (
                <section className="mt-3 grid gap-3">
                  <div className="grid grid-cols-2 gap-2">
                    {evidenceItems.map((item) => (
                      <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                        <div className="text-[11px] font-medium text-slate-500">{item.label}</div>
                        <div className="mt-1 text-base font-semibold text-slate-950">{item.value}</div>
                      </div>
                    ))}
                  </div>
                  <RelationObjectsCard relationSections={relationSections} />
                </section>
              )}
            </div>
          )}

          <div className="border-t border-slate-100 bg-white p-3">
            <Button
              variant="outline"
              onClick={() => {
                setLoading(true);
                void bitable.base.getSelection().then((next) => setSelection(next));
              }}
              className="w-full"
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
