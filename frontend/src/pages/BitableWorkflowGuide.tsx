import { ExternalLink, TableProperties, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";

const steps = [
  "构建并部署 `dist/bitable.html`，它才是多维表格内嵌脚本入口。",
  "在飞书多维表格里添加扩展脚本，并把脚本地址指向部署后的 `bitable.html`。",
  "在 Base 中打开「分析任务」表，选中任务行后，右侧脚本面板会直接展示执行轨道。",
];

export default function BitableWorkflowGuide() {
  return (
    <div className="min-h-full bg-[linear-gradient(180deg,rgba(248,250,252,0.98),rgba(255,255,255,1))] px-6 py-8 text-slate-900">
      <div className="mx-auto max-w-5xl space-y-6">
        <section className="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="max-w-3xl">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
                <Workflow className="h-4 w-4" />
                Workflow Entry Deprecated
              </div>
              <h1 className="mt-3 text-3xl font-semibold text-slate-950">七岗工作流已切到多维表格内嵌承载</h1>
              <p className="mt-3 text-sm leading-7 text-slate-600">
                这里不再承担真实执行界面。独立 `/workflow` 页面仅保留迁移说明，实际效果必须通过飞书多维表格扩展脚本加载，并在 Base
                内部展示。
              </p>
            </div>
            <div className="rounded-[24px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              主入口：`bitable.html`
            </div>
          </div>
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-500">
              <TableProperties className="h-4 w-4" />
              Bitable First
            </div>
            <h2 className="mt-3 text-2xl font-semibold text-slate-950">接入方式</h2>
            <div className="mt-5 space-y-3">
              {steps.map((step, index) => (
                <div key={step} className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-400">0{index + 1}</div>
                  <div className="mt-2 text-sm leading-7 text-slate-700">{step}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
            <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Docs Alignment</div>
            <h2 className="mt-3 text-2xl font-semibold text-slate-950">为什么必须这么做</h2>
            <div className="mt-4 space-y-4 text-sm leading-7 text-slate-600">
              <p>
                当前仓库采用的是 `@lark-base-open/js-sdk`。这个 SDK 本身就是给“多维表格扩展脚本”使用的，不是给普通独立站点页面直接嵌入 Base
                表格主体区域使用的。
              </p>
              <p>
                所以你要的“像图里那样在多维表格里面看到执行工作流”，正确落点就是 Base 内部的扩展脚本面板，而不是单独起一个 `/workflow`
                页面。
              </p>
              <p>仓库里已经新增 `src/bitable-main.tsx` 和 `bitable.html` 作为这个承载入口。</p>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              <Button asChild variant="outline">
                <a href="/bitable.html" target="_blank" rel="noreferrer">
                  打开嵌入入口
                  <ExternalLink className="ml-2 h-4 w-4" />
                </a>
              </Button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
