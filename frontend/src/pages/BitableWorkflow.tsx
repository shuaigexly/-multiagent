import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  CheckCircle2,
  Clock,
  Database,
  ExternalLink,
  Loader2,
  Pause,
  Play,
  PlusCircle,
  RefreshCw,
  Zap,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { toast } from '@/hooks/use-toast';
import {
  getStatus,
  listRecords,
  seedTask,
  setupWorkflow,
  startWorkflow,
  stopWorkflow,
  subscribeTaskProgress,
  type ProgressEvent,
  type TaskRecord,
  type WorkflowSetup,
} from '@/services/workflow';

interface LiveEvent {
  taskId: string;
  stage: string;
  progress: number;
  status: 'running' | 'done' | 'error';
  updatedAt: string;
}

const STATUS_STYLE: Record<string, string> = {
  待分析: 'bg-gray-100 text-gray-700',
  分析中: 'bg-yellow-100 text-yellow-700',
  已完成: 'bg-green-100 text-green-700',
  已归档: 'bg-blue-100 text-blue-700',
};

export default function BitableWorkflow() {
  const [setup, setSetupState] = useState<WorkflowSetup | null>(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [liveEvents, setLiveEvents] = useState<Record<string, LiveEvent>>({});
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskBackground, setNewTaskBackground] = useState('');
  const progressSubscriptionsRef = useRef<Map<string, () => void>>(new Map());

  // 初次加载：拉取 workflow 状态
  useEffect(() => {
    (async () => {
      try {
        const st = await getStatus();
        setRunning(st.running);
        if (st.state?.app_token && st.state?.table_ids) {
          setSetupState({
            app_token: st.state.app_token,
            url: st.state.url || '',
            table_ids: st.state.table_ids as WorkflowSetup['table_ids'],
          });
        }
      } catch (err) {
        console.warn('getStatus failed', err);
      }
    })();
  }, []);

  // 拉取任务列表
  const refreshTasks = async () => {
    if (!setup) return;
    try {
      const { records } = await listRecords(setup.app_token, setup.table_ids.task);
      setTasks(records);
    } catch (err) {
      toast({ title: '拉取任务失败', description: String(err), variant: 'destructive' });
    }
  };

  useEffect(() => {
    if (!setup) return;
    refreshTasks();
    const iv = setInterval(refreshTasks, 15_000);
    return () => clearInterval(iv);
  }, [setup]);

  // 为所有「分析中」任务订阅 SSE 进度
  useEffect(() => {
    if (!setup) {
      progressSubscriptionsRef.current.forEach((unsubscribe) => unsubscribe());
      progressSubscriptionsRef.current.clear();
      return;
    }
    const analyzingIds = new Set(
      tasks
        .filter((t) => (t.fields?.状态 as string) === '分析中')
        .map((t) => t.record_id),
    );

    for (const [recordId, unsubscribe] of progressSubscriptionsRef.current) {
      if (!analyzingIds.has(recordId)) {
        unsubscribe();
        progressSubscriptionsRef.current.delete(recordId);
      }
    }

    analyzingIds.forEach((recordId) => {
      if (progressSubscriptionsRef.current.has(recordId)) return;
      const unsubscribe = subscribeTaskProgress(recordId, (e: ProgressEvent) => {
        setLiveEvents((prev) => ({
          ...prev,
          [e.task_id]: {
            taskId: e.task_id,
            stage: (e.payload.stage as string) || e.event_type,
            progress: (e.payload.progress as number) ?? 0,
            status:
              e.event_type === 'task.done'
                ? 'done'
                : e.event_type === 'task.error'
                  ? 'error'
                  : 'running',
            updatedAt: e.ts,
          },
        }));
      });
      progressSubscriptionsRef.current.set(recordId, unsubscribe);
    });
  }, [setup, tasks]);

  useEffect(() => () => {
    progressSubscriptionsRef.current.forEach((unsubscribe) => unsubscribe());
    progressSubscriptionsRef.current.clear();
  }, []);

  const handleSetup = async () => {
    setLoading(true);
    try {
      const r = await setupWorkflow();
      setSetupState(r);
      toast({ title: '多维表格创建成功', description: r.url });
    } catch (err) {
      toast({ title: '创建失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleStart = async () => {
    if (!setup) return;
    setLoading(true);
    try {
      await startWorkflow(setup.app_token, setup.table_ids);
      setRunning(true);
      toast({ title: '调度器已启动', description: '轮询间隔 30 秒' });
    } catch (err) {
      toast({ title: '启动失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopWorkflow();
      setRunning(false);
      toast({ title: '调度器已停止' });
    } catch (err) {
      toast({ title: '停止失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleSeed = async () => {
    if (!setup || !newTaskTitle.trim()) return;
    try {
      await seedTask(
        setup.app_token,
        setup.table_ids.task,
        newTaskTitle.trim(),
        '综合分析',
        newTaskBackground.trim(),
      );
      setNewTaskTitle('');
      setNewTaskBackground('');
      toast({ title: '任务已写入', description: '调度器下次轮询时领取' });
      refreshTasks();
    } catch (err) {
      toast({ title: '写入失败', description: String(err), variant: 'destructive' });
    }
  };

  const summary = useMemo(() => {
    const by: Record<string, number> = {};
    tasks.forEach((t) => {
      const s = (t.fields?.状态 as string) || '未知';
      by[s] = (by[s] || 0) + 1;
    });
    return by;
  }, [tasks]);

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* 顶部标题 + 控制区 */}
      <div className="flex flex-col gap-4 rounded-lg border border-border bg-card p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-foreground">七岗多智能体 · 多维表格工作流</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              每条任务触发 Wave1（5 岗并行）→ Wave2（财务顾问）→ Wave3（CEO 助理）的 DAG 流水线，
              结果写入飞书多维表格并通过 SSE 实时推送进度。
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {!setup ? (
              <Button onClick={handleSetup} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
                初始化多维表格
              </Button>
            ) : running ? (
              <Button variant="outline" onClick={handleStop} disabled={loading}>
                <Pause className="h-4 w-4" /> 停止调度
              </Button>
            ) : (
              <Button onClick={handleStart} disabled={loading}>
                <Play className="h-4 w-4" /> 启动调度
              </Button>
            )}
            <Button variant="ghost" onClick={refreshTasks} disabled={!setup}>
              <RefreshCw className="h-4 w-4" /> 刷新
            </Button>
          </div>
        </div>

        {setup && (
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <a
              href={setup.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              打开多维表格 <ExternalLink className="h-3.5 w-3.5" />
            </a>
            <span className="text-muted-foreground">
              调度状态：
              <span className={running ? 'ml-1 text-success' : 'ml-1 text-muted-foreground'}>
                {running ? '● 运行中' : '○ 已停止'}
              </span>
            </span>
            <span className="text-muted-foreground">
              app_token: <code className="ml-1 rounded bg-secondary px-1 text-xs">{setup.app_token}</code>
            </span>
          </div>
        )}
      </div>

      {setup && (
        <>
          {/* 统计卡 */}
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: '待分析', key: '待分析', icon: Clock, color: 'text-gray-500' },
              { label: '分析中', key: '分析中', icon: Activity, color: 'text-yellow-500' },
              { label: '已完成', key: '已完成', icon: CheckCircle2, color: 'text-green-500' },
              { label: '已归档', key: '已归档', icon: Database, color: 'text-blue-500' },
            ].map((s) => {
              const Icon = s.icon;
              return (
                <div key={s.key} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">{s.label}</span>
                    <Icon className={`h-4 w-4 ${s.color}`} />
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-foreground">
                    {summary[s.key] || 0}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 添加任务 */}
          <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-foreground">+ 新增分析任务</h2>
            <div className="flex flex-col gap-3">
              <Input
                placeholder="任务标题，如：2026Q2 内容增长复盘"
                value={newTaskTitle}
                onChange={(e) => setNewTaskTitle(e.target.value)}
              />
              <Textarea
                placeholder="背景说明（可选）"
                rows={2}
                value={newTaskBackground}
                onChange={(e) => setNewTaskBackground(e.target.value)}
              />
              <Button className="self-start" onClick={handleSeed} disabled={!newTaskTitle.trim()}>
                <PlusCircle className="h-4 w-4" /> 写入任务
              </Button>
            </div>
          </div>

          {/* 任务列表 + 实时进度 */}
          <div className="rounded-lg border border-border bg-card p-5 shadow-sm">
            <div className="mb-3 flex items-center gap-2">
              <Zap className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">任务流（共 {tasks.length} 条）</h2>
            </div>
            {tasks.length === 0 ? (
              <div className="py-10 text-center text-sm text-muted-foreground">
                还没有任务。点击上方「+ 写入任务」或等待调度器领取种子任务。
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {tasks.map((t) => {
                  const status = (t.fields?.状态 as string) || '未知';
                  const title = (t.fields?.任务标题 as string) || '未命名';
                  const stage = (t.fields?.当前阶段 as string) || '';
                  const progress = ((t.fields?.进度 as number) || 0) * 100;
                  const live = liveEvents[t.record_id];
                  const displayStage = live?.stage || stage;
                  const displayProgress = live?.progress != null ? live.progress * 100 : progress;
                  return (
                    <div key={t.record_id} className="rounded-md border border-border/60 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span
                              className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${
                                STATUS_STYLE[status] || 'bg-gray-100 text-gray-600'
                              }`}
                            >
                              {status}
                            </span>
                            <span className="truncate text-sm font-medium text-foreground">{title}</span>
                          </div>
                          {displayStage && (
                            <div className="mt-1.5 text-xs text-muted-foreground">
                              {live && <span className="text-primary">● </span>}
                              {displayStage}
                            </div>
                          )}
                        </div>
                        {(t.fields?.优先级 as string) && (
                          <span className="shrink-0 text-xs text-muted-foreground">
                            {t.fields?.优先级 as string}
                          </span>
                        )}
                      </div>
                      {displayProgress > 0 && displayProgress < 100 && (
                        <div className="mt-2">
                          <Progress value={displayProgress} className="h-1.5" />
                          <div className="mt-1 text-right text-[10px] text-muted-foreground">
                            {displayProgress.toFixed(0)}%
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
