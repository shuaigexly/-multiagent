/**
 * v8.6.20-r49: 任务级操作工具栏 — 把 r34 / r43 / r44 三个新端点直接暴露成
 * 飞书插件里的按钮，让用户不用切换到 Swagger UI / CLI 就能：
 *
 *   - 「下载 Markdown」  → /api/v1/workflow/export/{record_id}?download=1
 *   - 「取消任务」     → /api/v1/workflow/cancel/{record_id}
 *   - 「复跑任务」     → /api/v1/workflow/replay/{record_id}?fresh=...
 *
 * 设计原则：
 *   - 操作前对 cancel / replay 弹原生 window.confirm（可逆程度低，避免误点）
 *   - 复跑提供 fresh checkbox 让用户决定是否清 LLM 缓存
 *   - 三按钮都做 inline status banner（成功 / 失败 / 加载中），不打扰主流
 *   - 任何失败都尽量给可读 detail（FastAPI HTTPException.detail）
 *   - 不持久任何 state — 状态由父组件刷新驱动
 */
import { useState } from "react";
import { Download, Ban, RotateCcw, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  cancelTask,
  downloadTaskMarkdown,
  replayTask,
  type CancelTaskResponse,
  type ReplayTaskResponse,
} from "@/services/workflow";

interface TaskActionsToolbarProps {
  recordId: string;
  appToken?: string;
  /** 任务当前状态 — 用于决定 cancel / replay 哪个该禁用。 */
  taskStatus?: string;
  /** 操作完成后回调（成功 / 失败均触发），父组件可用此刷新数据。 */
  onActionComplete?: (action: "cancel" | "replay" | "export", ok: boolean) => void;
}

type ToolbarStatus = {
  kind: "idle" | "loading" | "success" | "error";
  action?: "cancel" | "replay" | "export";
  message?: string;
};

function extractErrorMessage(err: unknown): string {
  // axios error → response.data.detail（FastAPI 标准形态）
  const e = err as { response?: { data?: { detail?: unknown }; status?: number }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const obj = detail as { message?: string };
    if (obj.message) return obj.message;
    return JSON.stringify(detail);
  }
  if (e?.response?.status) return `HTTP ${e.response.status}`;
  return e?.message || String(err);
}

export default function TaskActionsToolbar({
  recordId,
  appToken,
  taskStatus,
  onActionComplete,
}: TaskActionsToolbarProps) {
  const [status, setStatus] = useState<ToolbarStatus>({ kind: "idle" });
  const [freshReplay, setFreshReplay] = useState(false);

  const isInFlight = (taskStatus || "").includes("分析中");
  const isCompletedOrArchived = ["已完成", "已归档"].some((s) => (taskStatus || "").includes(s));

  const handleExport = async () => {
    setStatus({ kind: "loading", action: "export", message: "生成 Markdown 中…" });
    try {
      const { blobUrl, filename } = await downloadTaskMarkdown(recordId, appToken);
      // 触发浏览器下载
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      // 释放 blob URL（延迟一会再 revoke 以确保浏览器拿到了）
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1500);
      setStatus({ kind: "success", action: "export", message: `已下载 ${filename}` });
      onActionComplete?.("export", true);
    } catch (err) {
      setStatus({ kind: "error", action: "export", message: extractErrorMessage(err) });
      onActionComplete?.("export", false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm(`确认取消任务 ${recordId}？\n该操作不可逆，下一个 agent 入口会立即终止。`)) {
      return;
    }
    setStatus({ kind: "loading", action: "cancel", message: "提交取消信号…" });
    try {
      const resp: CancelTaskResponse = await cancelTask(recordId, appToken);
      const msg = resp.already_pending
        ? "任务已在取消队列中"
        : resp.bitable_marked
          ? "已标记 Bitable 异常状态 = 用户取消"
          : "已加入取消队列（Bitable 主表未同步）";
      setStatus({ kind: "success", action: "cancel", message: msg });
      onActionComplete?.("cancel", true);
    } catch (err) {
      setStatus({ kind: "error", action: "cancel", message: extractErrorMessage(err) });
      onActionComplete?.("cancel", false);
    }
  };

  const handleReplay = async () => {
    const confirmMsg = freshReplay
      ? `确认复跑任务 ${recordId}（清 LLM 缓存强制重打）？`
      : `确认复跑任务 ${recordId}（复用已有 LLM 缓存）？`;
    if (!window.confirm(confirmMsg)) return;
    setStatus({ kind: "loading", action: "replay", message: "重置任务状态…" });
    try {
      const resp: ReplayTaskResponse = await replayTask(recordId, {
        app_token: appToken,
        fresh: freshReplay,
      });
      const cleared = resp.cache_entries_cleared > 0
        ? `（清 ${resp.cache_entries_cleared} 条 agent 缓存）`
        : "";
      setStatus({
        kind: "success",
        action: "replay",
        message: `已从「${resp.previous_status}」回到「待分析」${cleared}，30s 内调度循环接手`,
      });
      onActionComplete?.("replay", true);
    } catch (err) {
      setStatus({ kind: "error", action: "replay", message: extractErrorMessage(err) });
      onActionComplete?.("replay", false);
    }
  };

  return (
    <div className="rounded-2xl border border-slate-200 bg-white/95 p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium uppercase tracking-[0.18em] text-slate-500">
          任务操作
        </div>
        {taskStatus && (
          <span className="text-xs text-slate-500">
            当前状态：<span className="font-mono text-slate-700">{taskStatus}</span>
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleExport}
          disabled={status.kind === "loading"}
          className="gap-1.5"
          title="下载完整任务报告 Markdown（含 CEO 综合 + 七岗输出 + 证据链 + 行动项）"
        >
          {status.kind === "loading" && status.action === "export" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          下载 Markdown
        </Button>

        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleCancel}
          disabled={!isInFlight || status.kind === "loading"}
          className="gap-1.5 border-rose-300 text-rose-700 hover:bg-rose-50"
          title={isInFlight ? "中止 in-flight 任务，停止后续 agent 调用" : "仅在「分析中」状态下可用"}
        >
          {status.kind === "loading" && status.action === "cancel" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Ban className="h-3.5 w-3.5" />
          )}
          取消任务
        </Button>

        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={handleReplay}
          disabled={isInFlight || status.kind === "loading"}
          className="gap-1.5 border-violet-300 text-violet-700 hover:bg-violet-50"
          title={isInFlight ? "请先取消，再复跑" : "把已完成 / 已取消 / 已归档的任务回到「待分析」让调度循环重跑"}
        >
          {status.kind === "loading" && status.action === "replay" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RotateCcw className="h-3.5 w-3.5" />
          )}
          {isCompletedOrArchived ? "复跑任务" : "复跑（fix 后）"}
        </Button>

        <label className="flex items-center gap-1.5 text-xs text-slate-600 cursor-pointer">
          <input
            type="checkbox"
            checked={freshReplay}
            onChange={(e) => setFreshReplay(e.target.checked)}
            disabled={status.kind === "loading"}
            className="h-3.5 w-3.5 rounded border-slate-300"
          />
          fresh（清 LLM 缓存）
        </label>
      </div>

      {status.kind === "loading" && (
        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/80 px-3 py-2 text-sm text-slate-700">
          {status.message}
        </div>
      )}
      {status.kind === "success" && (
        <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50/90 px-3 py-2 text-sm text-emerald-700">
          ✓ {status.message}
        </div>
      )}
      {status.kind === "error" && (
        <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/90 px-3 py-2 text-sm text-rose-700">
          ✗ {status.message}
        </div>
      )}
    </div>
  );
}
