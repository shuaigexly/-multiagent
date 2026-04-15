import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Inbox, Loader2, Plus } from 'lucide-react';
import { listTasks } from '../services/api';
import type { TaskListItem } from '../services/types';
import { Button } from '@/components/ui/button';

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  done: { label: '已完成', cls: 'bg-success/10 text-success' },
  running: { label: '执行中', cls: 'bg-warning/10 text-warning' },
  failed: { label: '失败', cls: 'bg-destructive/10 text-destructive' },
  pending: { label: '等待中', cls: 'bg-secondary text-secondary-foreground' },
  planning: { label: '规划中', cls: 'bg-info/10 text-info' },
};

function formatRelativeTime(v: string) {
  const diff = new Date(v).getTime() - Date.now();
  const fmt = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' });
  const m = Math.round(diff / 60000);
  if (Math.abs(m) < 60) return fmt.format(m, 'minute');
  const h = Math.round(m / 60);
  if (Math.abs(h) < 24) return fmt.format(h, 'hour');
  return fmt.format(Math.round(h / 24), 'day');
}

export default function History() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTasks().then(setTasks).catch(() => setError('加载失败')).finally(() => setLoading(false));
  }, []);

  return (
    <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">历史任务</h1>
          <p className="mt-1 text-sm text-muted-foreground">回看任务执行状态和生成结果</p>
        </div>
        <span className="text-xs text-muted-foreground">{tasks.length} 个任务</span>
      </div>

      {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

      {loading ? (
        <div className="flex items-center justify-center py-20 gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />加载中...
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-accent-foreground">
            <Inbox className="h-6 w-6" />
          </div>
          <div className="space-y-1">
            <div className="text-base font-medium text-foreground">暂无历史任务</div>
            <p className="text-sm text-muted-foreground">创建第一个 AI 工作流</p>
          </div>
          <Button variant="outline" onClick={() => navigate('/')}><Plus className="h-3.5 w-3.5" />创建任务</Button>
        </div>
      ) : (
        <div className="space-y-2.5">
          {tasks.map((t) => {
            const s = STATUS_MAP[t.status] ?? { label: t.status, cls: 'bg-secondary text-secondary-foreground' };
            const canNav = t.status !== 'pending' && t.status !== 'planning';
            return (
              <div
                key={t.id}
                className={`flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3 shadow-sm transition-all ${canNav ? 'cursor-pointer hover:bg-card hover:shadow-md' : 'opacity-60'}`}
                onClick={() => canNav && navigate(`/results/${t.id}`)}
                role={canNav ? 'button' : undefined}
                tabIndex={canNav ? 0 : -1}
              >
                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-center gap-1.5">
                    {t.task_type_label && <span className="rounded bg-accent px-1.5 py-0.5 text-[11px] text-accent-foreground font-medium">{t.task_type_label}</span>}
                    <span className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${s.cls}`}>{s.label}</span>
                  </div>
                  <p className="text-sm text-foreground line-clamp-1">{t.input_text || '基于上传文件创建'}</p>
                </div>
                <div className="text-right shrink-0 ml-4">
                  <div className="text-[11px] text-muted-foreground">{formatRelativeTime(t.created_at)}</div>
                  {canNav && <div className="text-[11px] text-primary mt-0.5">查看 →</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
