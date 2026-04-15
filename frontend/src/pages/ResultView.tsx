import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, ChevronDown, Loader2, FileText, BarChart3, MessageSquare, CheckSquare, Check, Presentation } from 'lucide-react';
import FeishuAssetCard from '../components/FeishuAssetCard';
import { AGENT_PERSONAS } from '../components/ModuleCard';
import { getTaskResults, publishTask } from '../services/api';
import { getChats } from '../services/feishu';
import type { FeishuChat } from '../services/feishu';
import type { AgentResult, TaskResultsResponse } from '../services/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  done: { label: '已完成', cls: 'bg-success/10 text-success' },
  running: { label: '执行中', cls: 'bg-warning/10 text-warning' },
  failed: { label: '失败', cls: 'bg-destructive/10 text-destructive' },
  pending: { label: '等待中', cls: 'bg-secondary text-secondary-foreground' },
  cancelled: { label: '已取消', cls: 'bg-secondary text-secondary-foreground' },
};

const PUBLISH_OPTIONS = [
  { value: 'doc', label: '飞书文档', desc: '完整分析报告', icon: FileText },
  { value: 'bitable', label: '多维表格', desc: '结构化数据', icon: BarChart3 },
  { value: 'slides', label: '演示文稿', desc: '汇报式展示', icon: Presentation },
  { value: 'message', label: '群消息', desc: '摘要通知', icon: MessageSquare },
  { value: 'task', label: '飞书任务', desc: '待办清单', icon: CheckSquare },
];

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

type ActionTaskState = 'idle' | 'loading' | 'success' | 'error';

export default function ResultView() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const copyResetTimerRef = useRef<number | null>(null);
  const [data, setData] = useState<TaskResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [publishTypes, setPublishTypes] = useState<string[]>(['doc', 'task']);
  const [docTitle, setDocTitle] = useState('');
  const [chatId, setChatId] = useState('');
  const [chats, setChats] = useState<FeishuChat[]>([]);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionTaskStates, setActionTaskStates] = useState<Map<string, ActionTaskState>>(new Map());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!taskId) { setLoading(false); return; }
    getChats().then(setChats).catch(() => {});
    getTaskResults(taskId)
      .then((r) => { setData(r); setExpandedAgent(r.agent_results[0]?.agent_id ?? null); })
      .catch(() => setError('加载结果失败'))
      .finally(() => setLoading(false));
  }, [taskId]);

  useEffect(() => () => {
    if (copyResetTimerRef.current) window.clearTimeout(copyResetTimerRef.current);
  }, []);

  const setActionTaskState = (item: string, state: ActionTaskState) => {
    setActionTaskStates((prev) => {
      const next = new Map(prev);
      next.set(item, state);
      return next;
    });
  };

  const createActionTask = async (item: string) => {
    if (!taskId || actionTaskStates.get(item) === 'loading') return;

    setActionTaskState(item, 'loading');

    try {
      await axios.post(`${BASE_URL}/api/v1/feishu/tasks`, { summary: item, source_task_id: taskId });
      setActionTaskState(item, 'success');
      window.setTimeout(() => setActionTaskState(item, 'idle'), 2000);
    } catch {
      setActionTaskState(item, 'error');
      window.setTimeout(() => setActionTaskState(item, 'idle'), 2000);
    }
  };

  const handlePublish = async () => {
    if (!taskId) return;
    if (publishTypes.includes('message') && !chatId) {
      setError('发送群消息必须先选择目标群聊');
      return;
    }
    setPublishing(true); setError(null);
    try {
      await publishTask(taskId, publishTypes, { docTitle: docTitle || undefined, chatId: chatId || undefined });
      setData(await getTaskResults(taskId));
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || '发布失败，请检查飞书配置');
    }
    finally { setPublishing(false); }
  };

  const buildMarkdown = (results: AgentResult[]) => results.map((result) => {
    const sections = result.sections
      .map((section) => `## ${section.title}\n\n${section.content}`)
      .join('\n\n');
    const actionItems = result.action_items.length > 0
      ? `\n\n## 行动建议\n${result.action_items.map((item) => `- ${item}`).join('\n')}`
      : '';

    return `# ${result.agent_name}\n\n${sections}${actionItems}\n\n---`;
  }).join('\n\n');

  const handleCopyMarkdown = async () => {
    if (!data || data.agent_results.length === 0) return;

    try {
      await navigator.clipboard.writeText(buildMarkdown(data.agent_results));
      setCopied(true);
      if (copyResetTimerRef.current) window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('复制失败，请检查浏览器权限');
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh] gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />正在加载...
    </div>
  );

  if (!data) return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3 text-center">
      <div className="text-4xl">📄</div>
      <div className="text-base font-medium text-foreground">任务结果不存在</div>
      <p className="text-sm text-muted-foreground">这个任务可能尚未完成，或 ID 无效。</p>
      <Button variant="outline" onClick={() => navigate('/')}>返回工作台</Button>
    </div>
  );

  const status = STATUS_MAP[data.status] ?? { label: data.status, cls: 'bg-secondary text-secondary-foreground' };

  return (
    <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
      {/* Header */}
      <div>
        <button onClick={() => navigate(-1)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mb-3">
          <ArrowLeft className="h-3.5 w-3.5" />返回
        </button>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-foreground">{data.task_type_label}结果报告</h1>
            <p className="text-[11px] text-muted-foreground mt-0.5">ID: {data.task_id}</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleCopyMarkdown} disabled={data.agent_results.length === 0}>
              {copied ? '已复制 ✓' : '复制 Markdown'}
            </Button>
            <span className={`rounded px-2 py-0.5 text-xs font-medium ${status.cls}`}>{status.label}</span>
          </div>
        </div>
      </div>

      {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

      {/* Summary */}
      {data.result_summary && (
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="text-xs font-medium text-muted-foreground mb-1.5">摘要</div>
          <p className="text-sm text-foreground leading-relaxed pl-3 border-l-2 border-primary">{data.result_summary}</p>
        </div>
      )}

      {/* Agent results */}
      <div className="space-y-2">
        <h2 className="text-sm font-medium text-foreground">各模块分析</h2>
        {data.agent_results.map((result) => {
          const open = expandedAgent === result.agent_id;
          const p = AGENT_PERSONAS[result.agent_id];
          return (
            <div key={result.agent_id} className="rounded-lg border border-border bg-card overflow-hidden">
              <button
                type="button"
                className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-secondary/50 transition-colors"
                onClick={() => setExpandedAgent(open ? null : result.agent_id)}
              >
                <div className="flex items-center gap-2.5">
                  <div className="flex h-7 w-7 items-center justify-center rounded-md text-xs font-medium text-primary-foreground"
                    style={{ backgroundColor: p?.color ?? '#636366' }}>
                    {p?.avatar ?? result.agent_name[0]}
                  </div>
                  <div>
                    <div className="text-sm font-medium text-foreground">{p?.name ?? result.agent_name}</div>
                    <div className="text-[11px] text-muted-foreground">{result.sections.length} 章节{result.action_items.length > 0 ? ` · ${result.action_items.length} 行动项` : ''}</div>
                  </div>
                </div>
                <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} />
              </button>
              {open && (
                <div className="px-4 pb-4 border-t border-border space-y-3 pt-3">
                  {result.sections.map((s) => (
                    <div key={s.title}>
                      <div className="text-xs font-medium text-foreground mb-1">{s.title}</div>
                      <p className="text-sm text-muted-foreground leading-relaxed whitespace-pre-wrap">{s.content}</p>
                    </div>
                  ))}
                  {result.action_items.length > 0 && (
                    <div>
                      <div className="text-xs font-medium text-foreground mb-1">行动项</div>
                      <ol className="space-y-1.5">
                        {result.action_items.map((item) => {
                          const actionTaskState = actionTaskStates.get(item) ?? 'idle';

                          return (
                            <li key={item} className="flex items-start gap-2">
                              <span className="flex-1 text-sm text-muted-foreground">{item}</span>
                              <div className="flex items-center gap-1.5">
                                <button
                                  type="button"
                                  disabled={actionTaskState === 'loading'}
                                  onClick={() => void createActionTask(item)}
                                  className="text-[11px] border border-border rounded px-2 py-0.5 hover:border-primary hover:text-primary transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  {actionTaskState === 'loading' ? '创建中...' : '→ 飞书任务'}
                                </button>
                                {actionTaskState === 'success' && (
                                  <span className="text-[11px] text-success">✓ 已创建</span>
                                )}
                                {actionTaskState === 'error' && (
                                  <span className="text-[11px] text-destructive">✗ 失败</span>
                                )}
                              </div>
                            </li>
                          );
                        })}
                      </ol>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Published */}
      {data.published_assets.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-sm font-medium text-foreground">已发布到飞书</h2>
          <div className="space-y-1.5">
            {data.published_assets.map((a, i) => <FeishuAssetCard key={`${a.type}-${a.id ?? i}`} asset={a} />)}
          </div>
        </div>
      )}

      {/* Publish */}
      {data.status === 'done' && (
        <div className="rounded-lg border border-border bg-card p-4 space-y-4">
          <div>
            <h2 className="text-sm font-medium text-foreground">发布到飞书</h2>
            <p className="text-[11px] text-muted-foreground mt-0.5">选择发布渠道</p>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            {PUBLISH_OPTIONS.map((opt) => {
              const sel = publishTypes.includes(opt.value);
              const Icon = opt.icon;
              return (
                <button key={opt.value} type="button"
                  onClick={() => setPublishTypes(c => c.includes(opt.value) ? c.filter(v => v !== opt.value) : [...c, opt.value])}
                  className={`relative flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors
                    ${sel ? 'border-primary bg-accent' : 'border-border hover:bg-secondary/50'}`}
                >
                  {sel && <div className="absolute top-2 right-2 h-4 w-4 rounded-full bg-primary flex items-center justify-center"><Check className="h-2.5 w-2.5 text-primary-foreground" /></div>}
                  <Icon className={`h-4 w-4 ${sel ? 'text-primary' : 'text-muted-foreground'}`} />
                  <div className="text-xs font-medium text-foreground">{opt.label}</div>
                  <div className="text-[11px] text-muted-foreground">{opt.desc}</div>
                </button>
              );
            })}
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] text-muted-foreground mb-1 block">文档标题</label>
              <Input value={docTitle} onChange={(e) => setDocTitle(e.target.value)} placeholder="4 月经营分析周报" />
            </div>
            <div>
              <label className={`text-[11px] mb-1 block ${publishTypes.includes('message') ? 'text-foreground font-medium' : 'text-muted-foreground'}`}>
                群聊{publishTypes.includes('message') ? <span className="text-destructive ml-0.5">*</span> : '（可选）'}
              </label>
              <select
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                className={`h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring
                  ${publishTypes.includes('message') && !chatId ? 'border-destructive focus:ring-destructive' : 'border-input'}`}
              >
                <option value="">请选择群聊</option>
                {chats.map((c) => (
                  <option key={c.chat_id} value={c.chat_id}>
                    {c.name}
                  </option>
                ))}
              </select>
              {publishTypes.includes('message') && !chatId && (
                <p className="text-[11px] text-destructive mt-0.5">发送群消息必须选择目标群聊</p>
              )}
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            {publishTypes.includes('message') && !chatId && (
              <span className="text-xs text-destructive">请先选择群聊，否则无法发布</span>
            )}
            <Button
              disabled={publishing || publishTypes.length === 0 || (publishTypes.includes('message') && !chatId)}
              onClick={handlePublish}
            >
              {publishing ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />发布中</> : '发布到飞书'}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
