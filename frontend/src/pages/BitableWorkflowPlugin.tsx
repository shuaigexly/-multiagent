import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FilterConjunction, FilterOperator, bitable, type IGetRecordsFilterInfo } from "@lark-base-open/js-sdk";
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  CircleDotDashed,
  Clock3,
  GitBranch,
  Loader2,
  Radio,
  ShieldAlert,
  Sparkles,
  TimerReset,
  Zap,
} from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { AGENT_PERSONAS } from "@/components/agentPersonas";
import { API_KEY_STORAGE_KEY, getRuntimeApiKey } from "@/services/http";
import { subscribeTaskProgress, type AgentPipelineSnapshot, type ProgressEvent } from "@/services/workflow";
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
  agentPipeline?: AgentPipelineSnapshot[];
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

function AgentFlowDashboard({
  agents,
  progress,
  stage,
  route,
  reviewAction,
  evidenceCount,
  pendingDataCount,
}: {
  agents: AgentPipelineSnapshot[];
  progress: number;
  stage: string;
  route: string;
  reviewAction: string;
  evidenceCount: number;
  pendingDataCount: number;
}) {
  const doneCount = agents.filter((agent) => agent.status === "done").length;
  const runningCount = agents.filter((agent) => agent.status === "running").length;
  const errorCount = agents.filter((agent) => agent.status === "error").length;
  const waves = ["Wave 1", "Wave 2", "Wave 3"];
  const waveCaptions: Record<string, string> = {
    "Wave 1": "五岗并行",
    "Wave 2": "财务接力",
    "Wave 3": "CEO 汇总",
  };

  return (
    <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-[linear-gradient(135deg,rgba(2,132,199,0.08),rgba(255,255,255,0.96)_44%,rgba(16,185,129,0.08))] p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
              <BrainCircuit className="h-4 w-4 text-sky-600" />
              Agent Command Deck
            </div>
            <div className="mt-2 text-2xl font-semibold leading-tight text-slate-950">七岗 AI 运行驾驶舱</div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
              <span className="rounded-full border border-slate-200 bg-white/80 px-3 py-1">{doneCount}/7 已完成</span>
              <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-sky-700">{runningCount || 0} 个运行中</span>
              {errorCount > 0 && <span className="rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-rose-700">{errorCount} 个异常</span>}
            </div>
          </div>
          <div className="min-w-40 rounded-2xl border border-white/80 bg-white/90 px-4 py-3 text-right shadow-sm">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Live Progress</div>
            <div className="mt-1 text-3xl font-semibold tabular-nums text-slate-950">{progress.toFixed(0)}%</div>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-4">
          {[
            { icon: Radio, label: "当前阶段", value: stage || "等待调度" },
            { icon: GitBranch, label: "路由", value: route || "待生成" },
            { icon: Zap, label: "评审动作", value: reviewAction || "待评审" },
            { icon: TimerReset, label: "证据 / 补数", value: `${evidenceCount} / ${pendingDataCount}` },
          ].map((item) => (
            <div key={item.label} className="rounded-2xl border border-white/80 bg-white/88 px-3 py-3 shadow-sm">
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-slate-400">
                <item.icon className="h-3.5 w-3.5 text-slate-500" />
                {item.label}
              </div>
              <div className="mt-2 line-clamp-2 text-sm font-medium leading-5 text-slate-800">{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-0 lg:grid-cols-[1.15fr_0.78fr_0.78fr]">
        {waves.map((wave, waveIndex) => {
          const waveAgents = agents.filter((agent) => agent.wave === wave);
          const waveDone = waveAgents.every((agent) => agent.status === "done");
          const waveRunning = waveAgents.some((agent) => agent.status === "running");
          const waveError = waveAgents.some((agent) => agent.status === "error");
          return (
            <div key={wave} className={`relative border-slate-200 p-4 ${waveIndex > 0 ? "border-t lg:border-l lg:border-t-0" : ""}`}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{wave}</div>
                  <div className="mt-1 text-base font-semibold text-slate-950">{waveCaptions[wave]}</div>
                </div>
                <div className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                  waveError ? AGENT_NODE_STYLE.error : waveDone ? AGENT_NODE_STYLE.done : waveRunning ? AGENT_NODE_STYLE.running : AGENT_NODE_STYLE.pending
                }`}>
                  {waveError ? "异常" : waveDone ? "完成" : waveRunning ? "运行中" : "排队"}
                </div>
              </div>
              <div className={wave === "Wave 1" ? "grid gap-2 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2" : "grid gap-2"}>
                {waveAgents.map((agent) => {
                  const persona = AGENT_PERSONAS[agent.key];
                  return (
                    <div key={agent.key} className={`rounded-2xl border px-3 py-3 transition-all ${AGENT_NODE_STYLE[agent.status]}`}>
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <div
                            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-sm font-semibold text-white ${agent.status === "running" ? "animate-pulse" : ""}`}
                            style={{ backgroundColor: persona?.color || "#64748b" }}
                          >
                            {persona?.avatar || agent.name.slice(0, 1)}
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-sm font-semibold text-slate-950">{agent.role}</div>
                            <div className="truncate text-xs text-slate-500">{agent.name}</div>
                          </div>
                        </div>
                        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-white/80">
                          {agent.status === "done" ? (
                            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                          ) : agent.status === "error" ? (
                            <ShieldAlert className="h-3.5 w-3.5 text-rose-600" />
                          ) : agent.status === "running" ? (
                            <Sparkles className="h-3.5 w-3.5 text-sky-600" />
                          ) : (
                            <CircleDotDashed className="h-3.5 w-3.5 text-slate-400" />
                          )}
                        </div>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <span className="rounded-full bg-white/80 px-2 py-0.5 text-[11px] font-medium">{AGENT_STATUS_LABEL[agent.status]}</span>
                        <span className="rounded-full bg-white/70 px-2 py-0.5 text-[11px] text-slate-500">{agent.dependency}</span>
                        {agent.fallback && (
                          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">兜底输出</span>
                        )}
                      </div>
                      <div className="mt-2 grid grid-cols-3 gap-1.5 text-[11px] text-slate-500">
                        <div className="rounded-lg bg-white/70 px-2 py-1">
                          <span className="block text-slate-400">耗时</span>
                          <span className="font-medium text-slate-700">{formatDurationMs(agent.duration_ms)}</span>
                        </div>
                        <div className="rounded-lg bg-white/70 px-2 py-1">
                          <span className="block text-slate-400">置信</span>
                          <span className="font-medium text-slate-700">{agent.confidence ? `${agent.confidence}/5` : "-"}</span>
                        </div>
                        <div className="rounded-lg bg-white/70 px-2 py-1">
                          <span className="block text-slate-400">证据</span>
                          <span className="font-medium text-slate-700">{agent.evidence_count ?? "-"}</span>
                        </div>
                      </div>
                      <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-600">
                        {agent.status === "error" ? agent.reason || agent.summary : agent.summary}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
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

        const relationLocator = buildResolvedRelationLocator(locator, currentTask);
        const seededReview = nextSourceKind === "review" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const seededActions = nextSourceKind === "action" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const seededArchives = nextSourceKind === "archive" && matchesRelatedRecord(selectedRecord, relationLocator) ? [selectedRecord] : [];
        const recordIdFilter = relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.review, "关联记录ID", relationLocator.taskRecordId)
          : null;
        const actionRecordIdFilter = relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.action, "关联记录ID", relationLocator.taskRecordId)
          : null;
        const archiveRecordIdFilter = relationLocator.taskRecordId
          ? await buildExactTextFilter(tableIds.archive, "关联记录ID", relationLocator.taskRecordId)
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

        const [reviewMatches, actionMatches, archiveMatches] = await Promise.all([
          collectMappedRecords(tableIds.review, (item) => matchesRelatedRecord(item, relationLocator), 1, seededReview, recordIdFilter || reviewTitleFilter || undefined),
          collectMappedRecords(tableIds.action, (item) => matchesRelatedRecord(item, relationLocator), 6, seededActions, actionRecordIdFilter || actionTitleFilter || undefined),
          collectMappedRecords(tableIds.archive, (item) => matchesRelatedRecord(item, relationLocator), 3, seededArchives, archiveRecordIdFilter || archiveTitleFilter || undefined),
        ]);
        if (!active) return;

        const currentReview = reviewMatches[0] || null;
        const currentActions = actionMatches.slice(0, 6);
        const currentArchives = archiveMatches.slice(0, 3);

        setTask(currentTask);
        setReview(currentReview);
        setActions(currentActions);
        setArchives(currentArchives);
        setResolutionDebug(buildResolutionDebug(nextSourceKind, selectedRecord, locator, currentTask));

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
                agentPipeline: event.payload.agent_pipeline || prev?.agentPipeline,
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
  const traceChainItems = useMemo(
    () => buildTraceChainItems(sourceKind, selectedRecordSnapshot, task, review, actions, archives, resolutionDebug),
    [actions, archives, resolutionDebug, review, selectedRecordSnapshot, sourceKind, task],
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

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,rgba(248,250,252,0.94),rgba(255,255,255,0.98))] p-4 text-slate-900">
      <div className="mx-auto max-w-6xl space-y-5">
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
              需要实时步骤流时，请先在同域站点写入{" "}
              <code className="rounded border border-amber-200 bg-white/70 px-1.5 py-0.5">
                localStorage["{API_KEY_STORAGE_KEY}"]
              </code>
              。
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

                <ResolutionCard resolutionDebug={resolutionDebug} resolutionStyle={RESOLUTION_STYLE} />
                <TraceChainCard nodes={traceChainItems} />
                <EntryContextCard
                  sourceKind={sourceKind}
                  sourceContextItems={sourceContextItems}
                  relationSummaryItems={relationSummaryItems}
                />
                <RelationObjectsCard relationSections={relationSections} />
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

                <ResolutionCard resolutionDebug={resolutionDebug} resolutionStyle={RESOLUTION_STYLE} />
                <TraceChainCard nodes={traceChainItems} />
                <EntryContextCard
                  sourceKind={sourceKind}
                  sourceContextItems={sourceContextItems}
                  relationSummaryItems={relationSummaryItems}
                />
                <RelationObjectsCard relationSections={relationSections} />

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

                <div className="mt-5">
                  <AgentFlowDashboard
                    agents={agentPipeline}
                    progress={progress}
                    stage={live?.stage || textValue(task.fields["当前阶段"]) || "等待调度"}
                    route={textValue(task.fields["工作流路由"]) || "待生成"}
                    reviewAction={reviewAction}
                    evidenceCount={numberValue(task.fields["证据条数"])}
                    pendingDataCount={numberValue(task.fields["需补数条数"])}
                  />
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
