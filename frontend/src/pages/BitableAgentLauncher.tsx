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
import { Loader2, Rocket, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

const DIMENSIONS = [
  "综合分析",
  "数据复盘",
  "内容战略",
  "增长优化",
  "产品规划",
  "风险评估",
  "财务诊断",
] as const;

const PRIORITIES = [
  { value: "P0 紧急", color: "bg-rose-100 text-rose-700 border-rose-200" },
  { value: "P1 高", color: "bg-orange-100 text-orange-700 border-orange-200" },
  { value: "P2 中", color: "bg-sky-100 text-sky-700 border-sky-200" },
  { value: "P3 低", color: "bg-slate-100 text-slate-700 border-slate-200" },
] as const;

const PURPOSES = [
  "直接汇报",
  "等待拍板",
  "直接执行",
  "补数复核",
  "重新分析",
] as const;

interface Props {
  onLaunched?: (recordId: string, taskTitle: string) => void;
}

export default function BitableAgentLauncher({ onLaunched }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [dimension, setDimension] = useState<typeof DIMENSIONS[number]>("综合分析");
  const [priority, setPriority] = useState<typeof PRIORITIES[number]["value"]>("P1 高");
  const [purpose, setPurpose] = useState<typeof PURPOSES[number]>("直接汇报");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState<{ recordId: string; title: string } | null>(null);

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
      const fieldByName = new Map(fields.map((f: { id: string; name: string }) => [f.name, f.id]));

      // 2. 构造写入字段（仅用 schema 已有的字段）
      const cellPayload: Record<string, unknown> = {};
      const setIfExists = (name: string, value: unknown) => {
        const fid = fieldByName.get(name);
        if (fid) cellPayload[fid] = value;
      };
      setIfExists("任务标题", title.trim());
      setIfExists("分析维度", dimension);
      setIfExists("优先级", priority);
      setIfExists("输出目的", purpose);
      setIfExists("背景说明", description.trim() || `用户在 plugin 内提交：${title.trim()}`);
      setIfExists("状态", "待分析");
      setIfExists("当前阶段", "🆕 用户从插件提交");
      setIfExists("进度", 0);
      setIfExists("任务来源", "插件提交");
      setIfExists("创建时间", new Date().toISOString().slice(0, 16).replace("T", " "));

      // 3. 写入 record
      const recordId = await table.addRecord({ fields: cellPayload });

      // 4. 选中该 record，让主面板自动绑定
      try {
        await bitable.base.setSelection({ tableId: table.id, recordId });
      } catch {
        // 部分 SDK 版本没有 setSelection，忽略
      }

      setSuccess({ recordId: String(recordId), title: title.trim() });
      onLaunched?.(String(recordId), title.trim());

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
    <div className="rounded-[28px] border border-slate-200 bg-[linear-gradient(135deg,rgba(125,211,252,0.10),rgba(255,255,255,0.98)_42%,rgba(196,181,253,0.10))] p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
            <Sparkles className="h-3.5 w-3.5 text-violet-500" />
            <span>Multi-Agent Launcher</span>
          </div>
          <div className="mt-2 text-2xl font-semibold text-slate-950">启动一次七岗 AI 协同分析</div>
          <div className="mt-2 text-sm leading-6 text-slate-600">
            告诉系统你要分析什么，调度器自动调用数据/内容/SEO/产品/运营/财务/CEO 七岗并行+依赖排序产出综合决策报告。
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-3">
        <label className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
          任务标题 <span className="text-rose-500">*</span>
          <input
            type="text"
            className="mt-1 block w-full rounded-xl border border-slate-200 bg-white/95 px-3 py-2.5 text-sm leading-6 text-slate-900 placeholder:text-slate-400 focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-200"
            placeholder="例如：Q3 财务健康度审视、竞品功能对标分析、用户留存漏斗诊断…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            disabled={submitting}
          />
        </label>

        <label className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
          背景说明（可选）
          <textarea
            rows={3}
            className="mt-1 block w-full rounded-xl border border-slate-200 bg-white/95 px-3 py-2.5 text-sm leading-6 text-slate-900 placeholder:text-slate-400 focus:border-violet-300 focus:outline-none focus:ring-2 focus:ring-violet-200"
            placeholder="把上下文 / 已知现状 / 数据源 等写下来，agent 会一并消化"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={2000}
            disabled={submitting}
          />
        </label>

        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
            分析维度
            <select
              className="mt-1 block w-full rounded-xl border border-slate-200 bg-white/95 px-3 py-2.5 text-sm leading-6 text-slate-900"
              value={dimension}
              onChange={(e) => setDimension(e.target.value as typeof DIMENSIONS[number])}
              disabled={submitting}
            >
              {DIMENSIONS.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
            优先级
            <select
              className="mt-1 block w-full rounded-xl border border-slate-200 bg-white/95 px-3 py-2.5 text-sm leading-6 text-slate-900"
              value={priority}
              onChange={(e) => setPriority(e.target.value as typeof PRIORITIES[number]["value"])}
              disabled={submitting}
            >
              {PRIORITIES.map((p) => (
                <option key={p.value} value={p.value}>{p.value}</option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
            输出目的
            <select
              className="mt-1 block w-full rounded-xl border border-slate-200 bg-white/95 px-3 py-2.5 text-sm leading-6 text-slate-900"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value as typeof PURPOSES[number])}
              disabled={submitting}
            >
              {PURPOSES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/90 px-3 py-2 text-sm text-rose-700">
          {error}
        </div>
      )}
      {success && (
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/90 px-3 py-2 text-sm text-emerald-700">
          ✓ 已写入「分析任务」表（{success.title}）。调度器会在下一轮 cycle 自动接手；右侧主面板会显示步骤详情。
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-slate-500 leading-5">
          下一步：调度循环每 30s 扫一次「待分析」队列，到达后会写入 7 岗输出 + CEO 综合报告 + 自动生成跟进任务。
        </div>
        <Button
          onClick={handleLaunch}
          disabled={submitting || !title.trim()}
          className="bg-violet-600 hover:bg-violet-700 text-white"
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
  );
}
