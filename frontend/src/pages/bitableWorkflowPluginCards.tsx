import type {
  WorkflowRelationSection,
  WorkflowResolutionDebug,
  WorkflowSourceKind,
  WorkflowSummaryItem,
  WorkflowTraceNode,
} from "./bitableWorkflowPluginUtils";
import { workflowSourceLabel } from "./bitableWorkflowPluginUtils";

const TRACE_NODE_STYLE: Record<WorkflowTraceNode["tone"], string> = {
  neutral: "border-slate-200 bg-white text-slate-700",
  active: "border-sky-200 bg-sky-50 text-sky-700",
  success: "border-emerald-200 bg-emerald-50 text-emerald-700",
  warning: "border-amber-200 bg-amber-50 text-amber-700",
};

export function EmptyState({ text }: { text: string }) {
  return <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50/80 px-3 py-4 text-sm leading-6 text-slate-500 shadow-sm">{text}</div>;
}

export function ResolutionCard({
  resolutionDebug,
  resolutionStyle,
}: {
  resolutionDebug: WorkflowResolutionDebug | null;
  resolutionStyle: Record<WorkflowResolutionDebug["resolutionMode"], string>;
}) {
  if (!resolutionDebug) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">Traceability</div>
          <div className="mt-1 text-base font-semibold text-slate-950">回溯诊断</div>
        </div>
        <div className={`shrink-0 rounded-md border px-2 py-1 text-[11px] font-medium ${resolutionStyle[resolutionDebug.resolutionMode]}`}>
          {resolutionDebug.resolutionLabel}
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {[
          `来源表：${resolutionDebug.sourceLabel}`,
          `当前记录ID：${resolutionDebug.selectedRecordId || "缺失"}`,
          `关联记录ID：${resolutionDebug.taskRecordIdCandidate || "缺失"}`,
          `任务标题：${resolutionDebug.taskTitleCandidate || "缺失"}`,
        ].map((item) => (
          <div key={item} className="rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2 text-xs leading-5 text-slate-600">
            {item}
          </div>
        ))}
      </div>
      {!!resolutionDebug.issues.length && (
        <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50/80 px-2.5 py-2 text-xs leading-5 text-rose-700">
          {resolutionDebug.issues.join("；")}
        </div>
      )}
    </div>
  );
}

export function EntryContextCard({
  sourceKind,
  sourceContextItems,
  relationSummaryItems,
}: {
  sourceKind: WorkflowSourceKind;
  sourceContextItems: WorkflowSummaryItem[];
  relationSummaryItems: WorkflowSummaryItem[];
}) {
  if (!sourceContextItems.length && !relationSummaryItems.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">Entry Context</div>
          <div className="mt-1 text-base font-semibold text-slate-950">当前记录</div>
        </div>
        <div className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600">
          {workflowSourceLabel(sourceKind)}
        </div>
      </div>
      <div className="mt-3 grid gap-2">
        {[...sourceContextItems, ...relationSummaryItems].map((item) => (
          <div key={`${item.label}:${item.value}`} className="rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2">
            <div className="text-[11px] font-medium text-slate-400">{item.label}</div>
            <div className="mt-1 text-sm leading-6 text-slate-700">{item.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function TraceChainCard({ nodes }: { nodes: WorkflowTraceNode[] }) {
  if (!nodes.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div>
        <div className="text-xs font-medium text-slate-500">Trace Chain</div>
        <div className="mt-1 text-base font-semibold text-slate-950">回溯链路</div>
      </div>
      <div className="mt-3 space-y-2">
        {nodes.map((node, index) => (
          <div key={node.key} className="relative pl-8">
            {index < nodes.length - 1 && <div className="absolute left-[13px] top-8 h-[calc(100%+0.5rem)] w-px bg-slate-200" />}
            <div className={`absolute left-0 top-1 flex h-7 w-7 items-center justify-center rounded-md border ${TRACE_NODE_STYLE[node.tone]}`}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50/70 px-2.5 py-2.5">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[11px] font-medium text-slate-400">{node.label}</div>
                  <div className="mt-1 truncate text-sm font-semibold text-slate-950">{node.title}</div>
                </div>
                <div className={`shrink-0 rounded-md border px-2 py-0.5 text-[10px] font-medium ${TRACE_NODE_STYLE[node.tone]}`}>
                  0{index + 1}
                </div>
              </div>
              <div className="mt-1.5 line-clamp-2 text-xs leading-5 text-slate-600">{node.caption}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RelationObjectsCard({ relationSections }: { relationSections: WorkflowRelationSection[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium text-slate-500">Related Objects</div>
          <div className="mt-1 text-base font-semibold text-slate-950">关联对象</div>
        </div>
        <div className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600">
          共 {relationSections.reduce((sum, section) => sum + section.count, 0)} 条
        </div>
      </div>
      <div className="mt-3 space-y-3">
        {relationSections.map((section) => (
          <div key={section.key} className="rounded-lg border border-slate-200 bg-slate-50/70 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-semibold text-slate-900">{section.label}</div>
              <div className="shrink-0 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600">
                {section.count} 条
              </div>
            </div>
            {!section.items.length ? (
              <div className="mt-2 text-sm leading-6 text-slate-500">{section.emptyText}</div>
            ) : (
              <div className="mt-2 space-y-2">
                {section.items.map((item) => (
                  <div key={item.key} className="rounded-lg border border-white/90 bg-white/95 p-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-slate-950">{item.title}</div>
                        <div className="mt-1 text-[11px] font-medium text-slate-400">{item.tableLabel}</div>
                      </div>
                      <div className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600">
                        {item.status}
                      </div>
                    </div>
                    <div className="mt-1.5 line-clamp-2 text-xs leading-5 text-slate-600">{item.summary}</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <span className="rounded-md border border-sky-200 bg-sky-50 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                        路由 · {item.route}
                      </span>
                      {item.chips.map((chip) => (
                        <span key={`${item.key}:${chip}`} className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600">
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
}
