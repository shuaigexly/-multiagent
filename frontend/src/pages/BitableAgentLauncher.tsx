/**
 * v8.6.20-r24：Agent 启动器面板（侧边栏顶部组件）
 *
 * 用户在这里输入「任务描述 / 分析维度 / 优先级」→ 一键写入「分析任务」表
 * → 调度循环自动接手 → 7 岗 DAG 跑分析 → record 状态实时刷新到 base
 * → BitableWorkflowPlugin 主面板自动绑定到这条新 record 显示步骤详情
 *
 * 模仿飞书原生 Bitable Agent 的"输入 → 步骤详情"形态。
 */
import { useState } from "react";
import { bitable } from "@lark-base-open/js-sdk";
import { CheckCircle2, ChevronDown, Loader2, Rocket, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  LAUNCHER_DIMENSIONS,
  LAUNCHER_OUTPUT_PURPOSES,
  LAUNCHER_PRIORITIES,
  buildLauncherRecordFields,
} from "./bitableAgentLauncherSchema";

interface Props {
  onLaunched?: (recordId: string, taskTitle: string) => void;
}

export default function BitableAgentLauncher({ onLaunched }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dimension, setDimension] = useState<typeof LAUNCHER_DIMENSIONS[number]>("综合分析");
  const [priority, setPriority] = useState<typeof LAUNCHER_PRIORITIES[number]["value"]>("P1 高");
  const [outputPurpose, setOutputPurpose] = useState<typeof LAUNCHER_OUTPUT_PURPOSES[number]>("经营诊断");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState<{ recordId: string; title: string } | null>(null);
  const [expanded, setExpanded] = useState(false);

  async function handleLaunch() {
    setError("");
    setSuccess(null);
    if (!title.trim()) {
      setError("请输入任务标题");
      return;
    }
    setSubmitting(true);
    try {
      // 1. 找到「分析任务」表
      const table = await bitable.base.getTableByName("分析任务");
      const fields = await table.getFieldMetaList();

      // 2. 构造写入字段（仅写 schema 里允许编辑的字段，避开自动创建时间等只读字段）
      const cellPayload = buildLauncherRecordFields(fields, {
        title,
        description,
        dimension,
        priority,
        outputPurpose,
      });

      // 3. 写入 record
      const recordId = await table.addRecord({ fields: cellPayload });

      // 4. 选中该 record，让主面板自动绑定
      try {
        const baseWithSelection = bitable.base as typeof bitable.base & {
          setSelection?: (selection: { tableId: string; recordId: string }) => Promise<unknown>;
        };
        await baseWithSelection.setSelection?.({ tableId: table.id, recordId });
      } catch {
        // 部分 SDK 版本没有 setSelection，忽略
      }

      setSuccess({ recordId: String(recordId), title: title.trim() });
      onLaunched?.(String(recordId), title.trim());
      setExpanded(false);

      // 重置表单
      setTitle("");
      setDescription("");
    } catch (err) {
      setError(`启动失败：${String(err)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-[0_8px_22px_rgba(15,23,42,0.06)]">
      <div className="h-1 bg-[linear-gradient(90deg,#3b82f6,#8b5cf6,#10b981)]" />
      <div className="p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[11px] font-medium text-slate-500">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-950 text-white shadow-sm">
                <Sparkles className="h-3.5 w-3.5" />
              </span>
              <span className="truncate">Multi-agent workflow</span>
            </div>
            <div className="mt-1 truncate text-base font-semibold text-slate-950">启动七岗分析</div>
          </div>
          <Button
            type="button"
            variant={expanded ? "secondary" : "default"}
            onClick={() => setExpanded((value) => !value)}
            size="sm"
            className={expanded ? "shrink-0" : "shrink-0 bg-slate-950 text-white hover:bg-slate-800"}
          >
            {expanded ? "收起" : "新建任务"}
            <ChevronDown className={`ml-1.5 h-4 w-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
          </Button>
        </div>

        {success && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/90 px-3 py-2 text-sm leading-6 text-emerald-700">
            <CheckCircle2 className="mt-1 h-3.5 w-3.5 shrink-0" />
            <span className="min-w-0 truncate">已写入「分析任务」表：{success.title}</span>
          </div>
        )}
      </div>

      {expanded && (
        <div className="border-t border-slate-100 bg-[#f8fafc] p-3">
          <div className="grid gap-3">
            <label className="text-xs font-medium text-slate-500">
              任务标题 <span className="text-rose-500">*</span>
              <input
                type="text"
                className="mt-1 block w-full rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-sm leading-6 text-slate-900 placeholder:text-slate-400 focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-200"
                placeholder="例如：用户留存漏斗诊断"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                maxLength={200}
                disabled={submitting}
              />
            </label>

            <label className="text-xs font-medium text-slate-500">
              背景说明（可选）
              <textarea
                rows={3}
                className="mt-1 block w-full rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-sm leading-6 text-slate-900 placeholder:text-slate-400 focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-200"
                placeholder="补充上下文、目标或数据源"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={2000}
                disabled={submitting}
              />
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs font-medium text-slate-500">
                分析维度
                <select
                  className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900"
                  value={dimension}
                  onChange={(e) => setDimension(e.target.value as typeof LAUNCHER_DIMENSIONS[number])}
                  disabled={submitting}
                >
                  {LAUNCHER_DIMENSIONS.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </label>
              <label className="text-xs font-medium text-slate-500">
                优先级
                <select
                  className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value as typeof LAUNCHER_PRIORITIES[number]["value"])}
                  disabled={submitting}
                >
                  {LAUNCHER_PRIORITIES.map((p) => (
                    <option key={p.value} value={p.value}>{p.value}</option>
                  ))}
                </select>
              </label>
              <label className="col-span-2 text-xs font-medium text-slate-500">
                输出目的
                <select
                  className="mt-1 block w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900"
                  value={outputPurpose}
                  onChange={(e) => setOutputPurpose(e.target.value as typeof LAUNCHER_OUTPUT_PURPOSES[number])}
                  disabled={submitting}
                >
                  {LAUNCHER_OUTPUT_PURPOSES.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {error && (
            <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50/90 px-3 py-2 text-sm text-rose-700">
              {error}
            </div>
          )}

          <div className="mt-3 flex">
            <Button
              onClick={handleLaunch}
              disabled={submitting || !title.trim()}
              className="w-full bg-slate-950 text-white hover:bg-slate-800"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  写入中…
                </>
              ) : (
                <>
                  <Rocket className="mr-2 h-4 w-4" />
                  启动七岗分析
                </>
              )}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
