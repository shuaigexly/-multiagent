import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  BarChart3,
  Check,
  CheckCircle2,
  CheckSquare,
  Copy,
  FileText,
  Layers,
  Loader2,
  MessageSquare,
  Presentation,
  Sparkles,
  Target,
} from 'lucide-react';
import { ErrorBoundary } from '../components/ErrorBoundary';
import FeishuAssetCard from '../components/FeishuAssetCard';
import { MarkdownContent } from '../components/MarkdownContent';
import type { StructuredChartBlock } from '../components/ResultCharts';
import { AGENT_PERSONAS } from '../components/agentPersonas';
import { getTaskResults, publishTask, getOAuthStatus, createFeishuTask } from '../services/api';
import { getChats } from '../services/feishu';
import type { FeishuChat } from '../services/feishu';
import type { AgentResult, ResultSection, TaskResultsResponse } from '../services/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { toast } from '@/components/ui/use-toast';

type ChartDataItem = { name: string; value: number; unit?: string };
type ChartBlock =
  | ChartDataItem[]
  | { chart_type: 'bar' | 'pie' | 'line' | 'radar'; title?: string; data: ChartDataItem[] };

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
  { value: 'card', label: '富卡片', desc: '群聊实时卡片', icon: Layers },
  { value: 'task', label: '飞书任务', desc: '待办清单', icon: CheckSquare },
];

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

type ActionTaskState = 'idle' | 'loading' | 'success' | 'error';
type SectionTone = 'risk' | 'insight' | 'action' | 'default';
const ResultCharts = lazy(() => import('../components/ResultCharts').then((module) => ({ default: module.ResultCharts })));

function extractMetrics(sections: ResultSection[]): Array<{ name: string; value: number }> {
  const metrics: Array<{ name: string; value: number }> = [];
  const pattern = /([^：:]+)[：:]\s*([0-9]+(?:\.[0-9]+)?)\s*(%|万|亿|个|次|元)?/g;
  for (const section of sections) {
    pattern.lastIndex = 0;
    let match;
    while ((match = pattern.exec(section.content)) !== null) {
      const name = match[1].trim().slice(-6);
      const value = parseFloat(match[2]);
      if (!Number.isNaN(value) && metrics.length < 6) {
        metrics.push({ name, value });
      }
    }
  }
  return metrics;
}

function isChartDataItem(item: unknown): item is ChartDataItem {
  return typeof item === 'object'
    && item !== null
    && 'name' in item
    && 'value' in item
    && typeof item.name === 'string'
    && typeof item.value === 'number';
}

function isStructuredChartBlock(block: unknown): block is StructuredChartBlock {
  return typeof block === 'object'
    && block !== null
    && 'chart_type' in block
    && 'data' in block
    && ['bar', 'pie', 'line', 'radar'].includes(String(block.chart_type))
    && Array.isArray(block.data)
    && block.data.every(isChartDataItem);
}

function getChartBlocks(result: AgentResult): StructuredChartBlock[] {
  const rawChartData = (result as AgentResult & { chart_data?: unknown }).chart_data;

  if (Array.isArray(rawChartData) && rawChartData.length > 0) {
    const first = rawChartData[0];

    if (isStructuredChartBlock(first)) {
      return rawChartData.filter(isStructuredChartBlock);
    }

    if (rawChartData.every(isChartDataItem)) {
      return [{ chart_type: 'bar', title: '关键指标', data: rawChartData }];
    }
  }

  const metrics = extractMetrics(result.sections);
  if (metrics.length >= 2) {
    return [{ chart_type: 'bar', title: '关键指标', data: metrics }];
  }

  return [];
}

function getSectionTone(title: string): SectionTone {
  if (title.includes('风险') || title.includes('⚠️')) return 'risk';
  if (title.includes('机会') || title.includes('结论') || title.includes('发现')) return 'insight';
  if (title.includes('建议') || title.includes('行动')) return 'action';
  return 'default';
}

function sectionToneClass(tone: SectionTone) {
  if (tone === 'risk') return 'border-orange-200 bg-orange-50/80 dark:border-orange-900/60 dark:bg-orange-950/20';
  if (tone === 'insight') return 'border-emerald-200 bg-emerald-50/80 dark:border-emerald-900/60 dark:bg-emerald-950/20';
  if (tone === 'action') return 'border-primary/20 bg-primary/5';
  return 'border-border bg-card';
}

function parseChecklistContent(content: string) {
  return content
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => line.replace(/^[-*•]\s+/, '').replace(/^\d+[.)、]\s*/, '').replace(/^\[[ xX]\]\s*/, ''))
    .filter(Boolean);
}

function getOrderedAgentResults(results: AgentResult[]) {
  return [...results].sort((left, right) => {
    if (left.agent_id === 'ceo_assistant') return -1;
    if (right.agent_id === 'ceo_assistant') return 1;
    return 0;
  });
}

function getPersona(result: AgentResult) {
  return AGENT_PERSONAS[result.agent_id] ?? {
    name: result.agent_name,
    title: 'AI 团队成员',
    avatar: result.agent_name.slice(0, 1),
    color: '#636366',
    personality: [],
    tagline: `${result.sections.length} 个分析章节`,
  };
}

function buildMarkdown(results: AgentResult[]) {
  return results.map((result) => {
    const sections = result.sections
      .map((section) => `## ${section.title}\n\n${section.content}`)
      .join('\n\n');
    const actionItems = result.action_items.length > 0
      ? `\n\n## 行动建议\n${result.action_items.map((item) => `- ${item}`).join('\n')}`
      : '';

    return `# ${result.agent_name}\n\n${sections}${actionItems}\n\n---`;
  }).join('\n\n');
}

function ActionTaskButton({
  item,
  state,
  onCreate,
}: {
  item: string;
  state: ActionTaskState;
  onCreate: (item: string) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        disabled={state === 'loading'}
        onClick={() => onCreate(item)}
        className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-60"
      >
        {state === 'loading' ? '创建中...' : '→ 飞书任务'}
      </button>
      {state === 'success' && <span className="text-[11px] text-success">✓ 已创建</span>}
      {state === 'error' && <span className="text-[11px] text-destructive">✗ 失败</span>}
    </div>
  );
}

function ActionChecklist({
  items,
  states,
  onCreate,
}: {
  items: string[];
  states: Map<string, ActionTaskState>;
  onCreate: (item: string) => void;
}) {
  return (
    <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
      <div className="mb-3 flex items-center gap-2">
        <CheckSquare className="h-4 w-4 text-primary" />
        <h4 className="text-sm font-semibold text-foreground">行动项清单</h4>
      </div>
      <ol className="space-y-2">
        {items.map((item) => {
          const state = states.get(item) ?? 'idle';

          return (
            <li key={item} className="flex flex-col gap-2 rounded-lg border border-border/70 bg-card/80 p-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex min-w-0 flex-1 items-start gap-2">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                </span>
                <span className="text-sm leading-relaxed text-muted-foreground">{item}</span>
              </div>
              <ActionTaskButton item={item} state={state} onCreate={onCreate} />
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function SectionCard({ section, isCeoSummary }: { section: ResultSection; isCeoSummary: boolean }) {
  const tone = isCeoSummary ? 'insight' : getSectionTone(section.title);
  const checklistItems = tone === 'action' ? parseChecklistContent(section.content) : [];

  return (
    <section className={`rounded-xl border p-4 shadow-sm ${isCeoSummary ? 'border-primary/30 bg-gradient-to-br from-primary/10 via-card to-card' : sectionToneClass(tone)}`}>
      <div className="mb-2 flex items-center gap-2">
        {tone === 'risk' && <span className="h-2 w-2 rounded-full bg-orange-500" />}
        {tone === 'insight' && <Sparkles className="h-3.5 w-3.5 text-emerald-600" />}
        {tone === 'action' && <Target className="h-3.5 w-3.5 text-primary" />}
        <h3 className="text-sm font-semibold text-foreground">{section.title}</h3>
      </div>
      {checklistItems.length > 1 ? (
        <ul className="space-y-2">
          {checklistItems.map((item) => (
            <li key={item} className="flex items-start gap-2 rounded-lg bg-card/70 px-3 py-2">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <MarkdownContent content={item} className="[&_p]:mb-0" />
            </li>
          ))}
        </ul>
      ) : (
        <MarkdownContent content={section.content} />
      )}
    </section>
  );
}

function ChartRenderer({ blocks }: { blocks: StructuredChartBlock[] }) {
  if (!blocks.length) return null;

  return (
    <Suspense fallback={<div className="rounded-lg border border-border/70 bg-card/70 p-4 text-sm text-muted-foreground">图表加载中...</div>}>
      <ResultCharts blocks={blocks} />
    </Suspense>
  );
}

function DataAnalystChart({ result }: { result: AgentResult }) {
  const chartBlocks = getChartBlocks(result);
  const numberedActionItems = result.action_items.filter((item) => /\d/.test(item)).slice(0, 3);

  if (chartBlocks.length === 0 && numberedActionItems.length === 0) return null;

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/70 p-4 dark:border-blue-900/60 dark:bg-blue-950/20">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold text-foreground">数据指标速览</h4>
          <p className="text-xs text-muted-foreground">自动识别报告中的数值型指标</p>
        </div>
        <BarChart3 className="h-5 w-5 text-primary" />
      </div>
      {chartBlocks.length > 0 && (
        <div className="overflow-x-auto">
          <ChartRenderer blocks={chartBlocks} />
        </div>
      )}
      {numberedActionItems.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {numberedActionItems.map((item) => (
            <span key={item} className="rounded-full bg-card px-2 py-1 text-[11px] text-muted-foreground ring-1 ring-border">
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentResultCard({
  result,
  actionTaskStates,
  onCreateActionTask,
}: {
  result: AgentResult;
  actionTaskStates: Map<string, ActionTaskState>;
  onCreateActionTask: (item: string) => void;
}) {
  const persona = getPersona(result);
  const isCeo = result.agent_id === 'ceo_assistant';

  return (
    <ErrorBoundary>
      <article className="overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
        <div className="h-1.5" style={{ backgroundColor: persona.color }} />
        <div
          className="border-b border-border px-5 py-4"
          style={{
            background: `linear-gradient(90deg, ${persona.color}1f 0%, transparent 76%)`,
          }}
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-base font-semibold text-primary-foreground shadow-sm"
                style={{ backgroundColor: persona.color }}
              >
                {persona.avatar}
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-semibold text-foreground">{persona.name}</h2>
                  <span className="rounded-full bg-card/80 px-2 py-0.5 text-[11px] font-medium text-muted-foreground ring-1 ring-border">
                    {persona.title}
                  </span>
                  {isCeo && (
                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                      优先呈现
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{persona.tagline}</p>
              </div>
            </div>
            <div className="text-xs text-muted-foreground">
              {result.sections.length} 章节
              {result.action_items.length > 0 ? ` · ${result.action_items.length} 行动项` : ''}
            </div>
          </div>
        </div>
        <div className="space-y-4 p-5">
          {result.sections.map((section) => (
            <SectionCard
              key={`${result.agent_id}-${section.title}`}
              section={section}
              isCeoSummary={isCeo && section.title.includes('管理摘要')}
            />
          ))}
          {result.agent_id === 'data_analyst' && <DataAnalystChart result={result} />}
          {result.action_items.length > 0 && (
            <ActionChecklist items={result.action_items} states={actionTaskStates} onCreate={onCreateActionTask} />
          )}
        </div>
      </article>
    </ErrorBoundary>
  );
}

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
  const [dmAvailable, setDmAvailable] = useState(false);
  const [chats, setChats] = useState<FeishuChat[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionTaskStates, setActionTaskStates] = useState<Map<string, ActionTaskState>>(new Map());
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!taskId) {
      setLoading(false);
      return;
    }

    getChats().then(setChats).catch(() => {});
    getOAuthStatus()
      .then((status) => {
        setDmAvailable(status?.authorized === true);
      })
      .catch(() => {});
    getTaskResults(taskId)
      .then(setData)
      .catch(() => setError('加载结果失败'))
      .finally(() => setLoading(false));
  }, [taskId]);

  useEffect(() => () => {
    if (copyResetTimerRef.current) window.clearTimeout(copyResetTimerRef.current);
  }, []);

  const orderedAgentResults = useMemo(() => getOrderedAgentResults(data?.agent_results ?? []), [data?.agent_results]);
  const ceoResult = orderedAgentResults.find((result) => result.agent_id === 'ceo_assistant');
  const ceoSummarySection = ceoResult?.sections.find((section) => section.title.includes('管理摘要'));

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
      await createFeishuTask(item, taskId);
      setActionTaskState(item, 'success');
      window.setTimeout(() => setActionTaskState(item, 'idle'), 2000);
    } catch {
      setActionTaskState(item, 'error');
      window.setTimeout(() => setActionTaskState(item, 'idle'), 2000);
    }
  };

  const handlePublish = async () => {
    if (!taskId) return;
    if ((publishTypes.includes('message') || publishTypes.includes('card')) && !chatId && !dmAvailable) {
      toast({
        title: '需要群 ID 或飞书授权',
        description: '请填写目标群 ID，或在设置页完成飞书 OAuth 授权',
        variant: 'destructive',
      });
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      await publishTask(taskId, publishTypes, { docTitle: docTitle || undefined, chatId: chatId || undefined });
      setData(await getTaskResults(taskId));
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg || '发布失败，请检查飞书配置');
    } finally {
      setPublishing(false);
    }
  };

  const handleCopyMarkdown = async () => {
    if (!data || data.agent_results.length === 0) return;

    try {
      await navigator.clipboard.writeText(buildMarkdown(orderedAgentResults));
      setCopied(true);
      if (copyResetTimerRef.current) window.clearTimeout(copyResetTimerRef.current);
      copyResetTimerRef.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError('复制失败，请检查浏览器权限');
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />正在加载...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
        <div className="text-4xl">📄</div>
        <div className="text-base font-medium text-foreground">任务结果不存在</div>
        <p className="text-sm text-muted-foreground">这个任务可能尚未完成，或 ID 无效。</p>
        <Button variant="outline" onClick={() => navigate('/')}>返回工作台</Button>
      </div>
    );
  }

  const status = STATUS_MAP[data.status] ?? { label: data.status, cls: 'bg-secondary text-secondary-foreground' };
  const needsFeishuTarget = publishTypes.includes('message') || publishTypes.includes('card');
  const missingFeishuTarget = needsFeishuTarget && !chatId && !dmAvailable;
  const useDmFallback = needsFeishuTarget && !chatId && dmAvailable;

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-5 py-6">
      <div>
        <button onClick={() => navigate(-1)} className="mb-3 flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft className="h-3.5 w-3.5" />返回
        </button>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-semibold text-foreground">{data.task_type_label}结果报告</h1>
              <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${status.cls}`}>{status.label}</span>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">ID: {data.task_id}</p>
          </div>
          <Button variant="outline" size="sm" onClick={handleCopyMarkdown} disabled={data.agent_results.length === 0}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
            {copied ? '已复制' : '复制 Markdown'}
          </Button>
        </div>
      </div>

      {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

      {data.result_summary && (
        <ErrorBoundary>
          <section className="relative overflow-hidden rounded-2xl border border-primary/20 bg-card p-6 shadow-sm">
            <div className="absolute inset-y-0 left-0 w-1.5 bg-primary" />
            <div className="absolute right-0 top-0 h-28 w-28 rounded-bl-full bg-primary/10" />
            <div className="relative">
              <div className="mb-2 flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <span className="text-xs font-semibold uppercase tracking-wide text-primary">Overall Summary</span>
              </div>
              <MarkdownContent content={data.result_summary} className="[&_p]:text-base [&_p]:text-foreground [&_p]:leading-7" />
            </div>
          </section>
        </ErrorBoundary>
      )}

      {ceoSummarySection && (
        <ErrorBoundary>
          <section className="rounded-2xl border border-slate-300 bg-gradient-to-br from-slate-900 to-slate-700 p-5 text-white shadow-sm dark:border-slate-700">
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15 text-sm font-semibold">
                {getPersona(ceoResult).avatar}
              </div>
              <div>
                <div className="text-sm font-semibold">CEO 助理 · 管理摘要</div>
                <div className="text-xs text-white/65">关键结论优先呈现，便于快速决策</div>
              </div>
            </div>
            <MarkdownContent
              content={ceoSummarySection.content}
              className="[&_p]:text-white/85 [&_strong]:text-white [&_li]:text-white/85 [&_h2]:text-white [&_h3]:text-white"
            />
          </section>
        </ErrorBoundary>
      )}

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground">各模块分析</h2>
          <span className="text-xs text-muted-foreground">{orderedAgentResults.length} 个智能体</span>
        </div>
        <div className="grid grid-cols-1 gap-4">
          {orderedAgentResults.map((result) => (
            <AgentResultCard
              key={result.agent_id}
              result={result}
              actionTaskStates={actionTaskStates}
              onCreateActionTask={(item) => void createActionTask(item)}
            />
          ))}
        </div>
      </div>

      {data.published_assets.length > 0 && (
        <ErrorBoundary>
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">已发布到飞书</h2>
            <div className="space-y-1.5">
              {data.published_assets.map((asset, index) => (
                <ErrorBoundary key={`${asset.type}-${asset.id ?? index}`}>
                  <FeishuAssetCard asset={asset} />
                </ErrorBoundary>
              ))}
            </div>
          </div>
        </ErrorBoundary>
      )}

      {data.status === 'done' && (
        <ErrorBoundary>
          <div className="rounded-2xl border border-border bg-card p-5 shadow-sm">
            <div className="mb-4">
              <h2 className="text-sm font-semibold text-foreground">发布到飞书</h2>
              <p className="mt-0.5 text-[11px] text-muted-foreground">选择发布渠道</p>
            </div>
            <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
              {PUBLISH_OPTIONS.map((option) => {
                const selected = publishTypes.includes(option.value);
                const Icon = option.icon;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setPublishTypes((current) => (
                      current.includes(option.value)
                        ? current.filter((value) => value !== option.value)
                        : [...current, option.value]
                    ))}
                    className={`relative flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors ${
                      selected ? 'border-primary bg-accent' : 'border-border hover:bg-secondary/50'
                    }`}
                  >
                    {selected && (
                      <div className="absolute right-2 top-2 flex h-4 w-4 items-center justify-center rounded-full bg-primary">
                        <Check className="h-2.5 w-2.5 text-primary-foreground" />
                      </div>
                    )}
                    <Icon className={`h-4 w-4 ${selected ? 'text-primary' : 'text-muted-foreground'}`} />
                    <div className="text-xs font-medium text-foreground">{option.label}</div>
                    <div className="text-[11px] text-muted-foreground">{option.desc}</div>
                  </button>
                );
              })}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-[11px] text-muted-foreground">文档标题</label>
                <Input value={docTitle} onChange={(event) => setDocTitle(event.target.value)} placeholder="4 月经营分析周报" />
              </div>
              <div>
                <label className={`mb-1 block text-[11px] ${needsFeishuTarget ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
                  群聊{missingFeishuTarget ? <span className="ml-0.5 text-destructive">*</span> : '（可选）'}
                </label>
                <select
                  value={chatId}
                  onChange={(event) => setChatId(event.target.value)}
                  className={`h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm focus:outline-none focus:ring-1 focus:ring-ring ${
                    missingFeishuTarget ? 'border-destructive focus:ring-destructive' : 'border-input'
                  }`}
                >
                  <option value="">请选择群聊</option>
                  {chats.map((chat) => (
                    <option key={chat.chat_id} value={chat.chat_id}>
                      {chat.name}
                    </option>
                  ))}
                </select>
                {useDmFallback && (
                  <p className="mt-1 text-xs text-amber-600">未填写群 ID，将通过私信发给已授权飞书用户</p>
                )}
                {missingFeishuTarget && (
                  <p className="mt-0.5 text-[11px] text-destructive">发送消息/卡片需填写群 ID，或先完成飞书 OAuth 授权</p>
                )}
              </div>
            </div>
            <div className="mt-4 flex items-center justify-end gap-2">
              {missingFeishuTarget && (
                <span className="text-xs text-destructive">请先填写群 ID 或完成飞书授权，否则无法发布</span>
              )}
              <Button disabled={publishing || publishTypes.length === 0 || missingFeishuTarget} onClick={handlePublish}>
                {publishing ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />发布中</> : '发布到飞书'}
              </Button>
            </div>
          </div>
        </ErrorBoundary>
      )}
    </div>
  );
}
