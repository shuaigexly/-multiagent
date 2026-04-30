import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Inbox, Loader2, Plus, Trash2 } from 'lucide-react';
import { deleteTask, listTasks } from '../services/api';
import type { TaskListItem } from '../services/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  done: { label: '已完成', cls: 'bg-success/10 text-success' },
  running: { label: '执行中', cls: 'bg-warning/10 text-warning' },
  failed: { label: '失败', cls: 'bg-destructive/10 text-destructive' },
  pending: { label: '等待中', cls: 'bg-secondary text-secondary-foreground' },
  planning: { label: '规划中', cls: 'bg-info/10 text-info' },
  cancelled: { label: '已取消', cls: 'bg-secondary text-secondary-foreground' },
};

const HISTORY_FETCH_LIMIT = 50;
const PAGE_SIZE = 10;
const ACTIVE_STATUSES = new Set(['planning', 'pending', 'running']);
const FILTER_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'active', label: '执行中' },
  { value: 'done', label: '已完成' },
  { value: 'failed', label: '失败' },
] as const;

type StatusFilter = (typeof FILTER_OPTIONS)[number]['value'];

function formatRelativeTime(v: string) {
  const diff = Date.now() - new Date(v).getTime();
  const fmt = new Intl.RelativeTimeFormat('zh-CN', { numeric: 'auto' });
  if (Math.abs(diff) < 60000) return '刚刚';
  const m = Math.round(diff / 60000);
  if (Math.abs(m) < 60) return fmt.format(-m, 'minute');
  const h = Math.round(m / 60);
  if (Math.abs(h) < 24) return fmt.format(-h, 'hour');
  return fmt.format(-Math.round(h / 24), 'day');
}

export default function History() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [page, setPage] = useState(1);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [canUseServerSearch, setCanUseServerSearch] = useState(false);
  const [usingServerSearch, setUsingServerSearch] = useState(false);
  const requestSeqRef = useRef(0);

  const loadTasks = async ({ search, initial = false }: { search?: string; initial?: boolean } = {}) => {
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError(null);

    try {
      const data = await listTasks({
        limit: search ? 100 : HISTORY_FETCH_LIMIT,
        search,
      });
      if (requestSeq !== requestSeqRef.current) return;
      setTasks(data);
      if (!search) {
        setCanUseServerSearch(data.length >= HISTORY_FETCH_LIMIT);
      }
    } catch {
      if (requestSeq !== requestSeqRef.current) return;
      setError(initial ? '加载失败' : '更新失败');
    } finally {
      if (requestSeq === requestSeqRef.current) {
        if (initial) {
          setLoading(false);
        } else {
          setRefreshing(false);
        }
      }
    }
  };

  useEffect(() => {
    void loadTasks({ initial: true });
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(searchText.trim());
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    if (debouncedSearch && canUseServerSearch) {
      setUsingServerSearch(true);
      void loadTasks({ search: debouncedSearch });
      return;
    }

    if (!debouncedSearch && usingServerSearch) {
      setUsingServerSearch(false);
      void loadTasks();
    }
  }, [debouncedSearch, canUseServerSearch, usingServerSearch]);

  useEffect(() => {
    const hasActiveTasks = !loading && tasks.some((task) => ACTIVE_STATUSES.has(task.status));

    if (!hasActiveTasks) {
      return;
    }

    const timer = window.setInterval(() => {
      void loadTasks({ search: usingServerSearch ? debouncedSearch : undefined });
    }, 5000);

    return () => window.clearInterval(timer);
  }, [debouncedSearch, loading, tasks, usingServerSearch]);

  const filteredTasks = useMemo(() => {
    const keyword = debouncedSearch.toLowerCase();

    return tasks.filter((task) => {
      const matchesSearch =
        !keyword || (task.input_text ?? '').toLowerCase().includes(keyword);

      if (!matchesSearch) {
        return false;
      }

      if (statusFilter === 'all') {
        return true;
      }
      if (statusFilter === 'active') {
        return ACTIVE_STATUSES.has(task.status);
      }
      return task.status === statusFilter;
    });
  }, [debouncedSearch, statusFilter, tasks]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch, statusFilter, tasks]);

  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / PAGE_SIZE));
  const pagedTasks = filteredTasks.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const hasFilters = Boolean(debouncedSearch) || statusFilter !== 'all';

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  const handleDelete = async (taskId: string) => {
    if (!window.confirm('确认删除这个任务吗？')) {
      return;
    }

    setDeletingTaskId(taskId);
    setError(null);
    try {
      await deleteTask(taskId);
      setTasks((prev) => prev.filter((task) => task.id !== taskId));
    } catch {
      setError('删除失败');
    } finally {
      setDeletingTaskId(null);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-foreground">历史任务</h1>
          <p className="mt-1 text-sm text-muted-foreground">回看任务执行状态和生成结果</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {refreshing && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          <span>共 {filteredTasks.length} 个任务</span>
        </div>
      </div>

      {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

      <div className="rounded-lg border border-border bg-card p-4 shadow-sm space-y-3">
        <Input
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          placeholder="搜索任务内容"
        />
        <div className="flex flex-wrap gap-2">
          {FILTER_OPTIONS.map((option) => (
            <Button
              key={option.value}
              type="button"
              size="sm"
              variant={statusFilter === option.value ? 'default' : 'outline'}
              onClick={() => setStatusFilter(option.value)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />加载中...
        </div>
      ) : tasks.length === 0 && !hasFilters ? (
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
      ) : filteredTasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-accent-foreground">
            <Inbox className="h-6 w-6" />
          </div>
          <div className="space-y-1">
            <div className="text-base font-medium text-foreground">未找到匹配任务</div>
            <p className="text-sm text-muted-foreground">试试调整搜索词或筛选条件</p>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="space-y-2.5">
            {pagedTasks.map((t) => {
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
                  <div className="flex items-center gap-3 shrink-0 ml-4">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={(event) => {
                        event.stopPropagation();
                        void handleDelete(t.id);
                      }}
                      disabled={deletingTaskId === t.id}
                      aria-label="删除任务"
                    >
                      {deletingTaskId === t.id ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </Button>
                    <div className="text-right">
                      <div className="text-[11px] text-muted-foreground">{formatRelativeTime(t.created_at)}</div>
                      {canNav && <div className="text-[11px] text-primary mt-0.5">查看 →</div>}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between rounded-lg border border-border bg-card px-4 py-3 shadow-sm">
              <span className="text-sm text-muted-foreground">
                第 {page} / {totalPages} 页
              </span>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={page === 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  上一页
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={page === totalPages}
                  onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                >
                  下一页
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
