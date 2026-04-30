import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Upload, FileText, X, Loader2, ArrowRight } from 'lucide-react';
import ModuleCard from '../components/ModuleCard';
import ExecutionTimeline from '../components/ExecutionTimeline';
import ContextSuggestions, { type Suggestion } from '../components/ContextSuggestions';
import { cancelTask, confirmTask, createSSEConnection, getTaskStatus, listAgents, submitTask } from '../services/api';
import { getConfig, isStoredLLMConfigured, setStoredLLMConfigured } from '../services/config';
import { getFeishuContext, getChats, type FeishuContext } from '../services/feishu';
import type { AgentInfo, SSEEvent, TaskPlanResponse } from '../services/types';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import {
  appendWorkbenchStreamEvent,
  isTerminalTaskStatus,
  parseWorkbenchStreamEvent,
  resolveStreamEndState,
  type WorkbenchStep,
} from './workbenchStreamState';

const ALL_AGENT_MODULES = [
  'data_analyst', 'finance_advisor', 'seo_advisor', 'content_manager',
  'product_manager', 'operations_manager', 'ceo_assistant',
];
const PRESET_COMBOS = [
  { label: '经营分析组', modules: ['data_analyst', 'finance_advisor', 'ceo_assistant'] },
  { label: '增长突破组', modules: ['seo_advisor', 'content_manager', 'operations_manager'] },
  { label: '立项评估组', modules: ['product_manager', 'finance_advisor', 'ceo_assistant'] },
  { label: '全明星阵容', modules: ALL_AGENT_MODULES },
];
const WORKFLOW_TEMPLATES = [
  {
    id: 'weekly_report',
    label: '周报生成',
    icon: '📊',
    desc: '自动汇总本周经营数据',
    prompt: '请分析本周经营数据，包括：\n1. 核心业务指标与上周对比\n2. 收入/成本/利润的主要波动点\n3. 识别出需要关注的风险信号\n4. 下周优先级行动建议（3-5条）\n最终输出一份适合发给管理层的周报。',
    modules: ['data_analyst', 'finance_advisor', 'ceo_assistant'],
  },
  {
    id: 'meeting_prep',
    label: '会前准备',
    icon: '📋',
    desc: '生成议题和预期结论',
    prompt: '请为即将召开的管理层会议准备材料，包括：\n1. 梳理本次会议的核心议题（3-5个）\n2. 每个议题的背景说明和讨论要点\n3. 预期需要做的决策和结论\n4. 会后跟进事项清单\n请以清晰的飞书文档格式输出。',
    modules: ['product_manager', 'operations_manager', 'ceo_assistant'],
  },
  {
    id: 'sprint_review',
    label: '迭代复盘',
    icon: '🔄',
    desc: '产品迭代回顾与规划',
    prompt: '请协助完成本迭代（Sprint）的复盘工作：\n1. 梳理本迭代完成/未完成的功能目标\n2. 分析延期/阻塞的根本原因\n3. 用户反馈和产品数据变化\n4. 下一迭代重点任务优先级排序\n5. 流程改进建议',
    modules: ['product_manager', 'data_analyst', 'operations_manager'],
  },
  {
    id: 'growth_analysis',
    label: '增长分析',
    icon: '🚀',
    desc: '识别增长机会与瓶颈',
    prompt: '请进行全面的增长分析：\n1. 流量/获客渠道效率对比\n2. 用户转化漏斗各环节流失分析\n3. 留存和活跃度趋势\n4. 识别 TOP3 增长机会和对应策略\n5. 内容/SEO 优化建议',
    modules: ['seo_advisor', 'content_manager', 'data_analyst'],
  },
];
type Step = WorkbenchStep;

function isSameSelection(a: string[], b: string[]) {
  return JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());
}

function buildSuggestions(ctx: FeishuContext, chats: Array<{ chat_id: string; name: string; description: string | null; chat_type: string }>): Suggestion[] {
  const suggestions: Suggestion[] = [];

  // Drive files → data analysis suggestions (up to 3)
  ctx.drive.slice(0, 3).forEach((f, i) => {
    suggestions.push({
      id: `doc-${i}`,
      type: 'doc',
      source: '飞书文档',
      label: f.name,
      prompt: `分析《${f.name}》，提取关键洞察和行动建议`,
      agents: ['data_analyst', 'ceo_assistant'],
    });
  });

  // Calendar events → meeting prep suggestions (up to 3)
  ctx.calendar.slice(0, 3).forEach((e, i) => {
    suggestions.push({
      id: `cal-${i}`,
      type: 'calendar',
      source: '日历',
      label: e.summary,
      prompt: `为《${e.summary}》准备会议材料，梳理议题和预期结论`,
      agents: ['product_manager', 'ceo_assistant'],
    });
  });

  // Pending tasks → execution plan suggestions (up to 3)
  ctx.tasks.filter(t => !t.completed).slice(0, 3).forEach((t, i) => {
    suggestions.push({
      id: `task-${i}`,
      type: 'task',
      source: '待办',
      label: t.summary,
      prompt: `推进「${t.summary}」，制定详细执行计划和关键节点`,
      agents: ['operations_manager', 'ceo_assistant'],
    });
  });

  // Chats → follow-up suggestions (up to 2)
  chats.slice(0, 2).forEach((c, i) => {
    suggestions.push({
      id: `chat-${i}`,
      type: 'chat',
      source: '群聊',
      label: c.name,
      prompt: `梳理「${c.name}」群聊中的待办和关键信息，生成跟进建议`,
      agents: ['operations_manager', 'ceo_assistant'],
    });
  });

  return suggestions;
}

export default function Workbench() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const streamSeqRef = useRef(0);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [inputText, setInputText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>('input');
  const [plan, setPlan] = useState<TaskPlanResponse | null>(null);
  const [selectedModules, setSelectedModules] = useState<string[]>([]);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feishuCtx, setFeishuCtx] = useState<FeishuContext | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [ctxLoading, setCtxLoading] = useState(true);
  const [feishuConfigured, setFeishuConfigured] = useState(false);
  const [selectedSuggestion, setSelectedSuggestion] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [userInstructions, setUserInstructions] = useState('');

  useEffect(() => {
    listAgents().then(setAgents).catch(() => setError('加载团队成员失败'));
    // 从后端同步 LLM 配置状态到 localStorage，确保 isStoredLLMConfigured() 准确
    // 同时检查飞书是否已配置
    getConfig().then(cfg => {
      setStoredLLMConfigured(Boolean(cfg.llm_api_key?.set));
      setFeishuConfigured(Boolean(cfg.feishu_app_id?.set && cfg.feishu_app_secret?.set));
    }).catch(() => {});
    Promise.all([
      getFeishuContext(),
      getChats().catch(() => [] as Array<{ chat_id: string; name: string; description: string | null; chat_type: string }>),
    ])
      .then(([ctx, chats]) => {
        setFeishuCtx(ctx);
        setSuggestions(buildSuggestions(ctx, chats.slice(0, 5)));
      })
      .catch(() => {})
      .finally(() => setCtxLoading(false));
  }, []);
  useEffect(() => () => {
    streamSeqRef.current += 1;
    eventSourceRef.current?.close();
  }, []);

  const toggleModule = (id: string) =>
    setSelectedModules(p => p.includes(id) ? p.filter(i => i !== id) : [...p, id]);

  const handleSuggestionSelect = (s: Suggestion) => {
    if (formLocked) return;
    setInputText(s.prompt);
    setSelectedModules(s.agents);
    setSelectedSuggestion(s.id);
  };

  const startSSE = async (tid: string, recover: 'input' | 'confirm') => {
    const streamSeq = streamSeqRef.current + 1;
    streamSeqRef.current = streamSeq;
    eventSourceRef.current?.close();
    const es = await createSSEConnection(tid);
    if (streamSeq !== streamSeqRef.current) {
      es.close();
      return;
    }
    eventSourceRef.current = es;
    es.onmessage = (e) => {
      if (eventSourceRef.current !== es) return;
      const d = parseWorkbenchStreamEvent(e.data);
      if (!d) return;
      if (!('sequence' in d)) {
        es.close();
        if (eventSourceRef.current === es) eventSourceRef.current = null;
        const result = resolveStreamEndState(d.status, recover);
        setStep(result.step);
        setError(result.error);
        setLoading(false);
        return;
      }
      setEvents(p => appendWorkbenchStreamEvent(p, d));
    };
    es.onerror = async () => {
      if (eventSourceRef.current !== es) return;
      es.close(); if (eventSourceRef.current === es) eventSourceRef.current = null;
      try {
        const s = await getTaskStatus(tid);
        if (isTerminalTaskStatus(s.status)) {
          const result = resolveStreamEndState(s.status, recover);
          setStep(result.step);
          setError(result.error);
        } else {
          setError('连接中断，请刷新页面');
        }
      } catch { setStep(recover); setError('连接中断'); }
      finally { setLoading(false); }
    };
  };

  const handleSubmit = async () => {
    if (!inputText.trim() && !file) { setError('请输入任务描述'); return; }
    if (!isStoredLLMConfigured()) { setError('请先前往「设置」页面配置 LLM API Key'); return; }
    setError(null); setEvents([]);
    if (selectedModules.length > 0) {
      setPlan(null); setLoading(true); setStep('running');
      try { const r = await submitTask(inputText, file ?? undefined, feishuCtx ?? undefined); setTaskId(r.task_id); await confirmTask(r.task_id, selectedModules); await startSSE(r.task_id, 'input'); }
      catch { setStep('input'); setError('执行失败'); setLoading(false); }
      return;
    }
    setLoading(true); setStep('planning');
    try { const r = await submitTask(inputText, file ?? undefined, feishuCtx ?? undefined); setPlan(r); setTaskId(r.task_id); setSelectedModules(r.selected_modules); setUserInstructions(''); setStep('confirm'); }
    catch { setStep('input'); setError('AI 组队失败'); }
    finally { setLoading(false); }
  };

  const handleCancel = async () => {
    if (!taskId || cancelling) return;
    setCancelling(true);
    setError(null);
    streamSeqRef.current += 1;
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    try {
      await cancelTask(taskId);
      setStep('input');
      setLoading(false);
      setEvents([]);
      setPlan(null);
      setTaskId(null);
      setUserInstructions('');
    } catch {
      setError('取消任务失败');
    } finally {
      setCancelling(false);
    }
  };

  const handleConfirm = async () => {
    if (!taskId || selectedModules.length === 0) { setError('请至少选择一名团队成员'); return; }
    setError(null); setLoading(true); setEvents([]); setStep('running');
    try { await confirmTask(taskId, selectedModules, userInstructions); await startSSE(taskId, 'confirm'); }
    catch { setLoading(false); setStep('confirm'); setError('执行失败'); }
  };

  const formLocked = step !== 'input';
  const selectionLocked = step === 'planning' || step === 'running' || step === 'done';
  const progressValue = step === 'done' ? 100 : step === 'running' ? Math.min(68 + events.length * 6, 94) : 35;

  const stepStates = (() => {
    if (step === 'done') return [2, 2, 2];
    if (step === 'running') return [2, 2, 1];
    if (step === 'planning' || step === 'confirm') return [2, 1, 0];
    return [1, 0, 0]; // 0=idle, 1=active, 2=done
  })();

  return (
    <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
      {/* Title row */}
      <div>
        <h1 className="text-xl font-semibold text-foreground">构建属于你的 AI 团队</h1>
        <p className="text-sm text-muted-foreground mt-1">选好你的团队，告诉他们任务目标，AI 帮你执行并输出到飞书。</p>
      </div>

      {/* Smart suggestions from Feishu context */}
      <ContextSuggestions
          suggestions={suggestions}
          loading={ctxLoading}
          selectedId={selectedSuggestion}
          onSelect={handleSuggestionSelect}
          disabled={formLocked}
          feishuConfigured={feishuConfigured}
        />

      {/* Workflow Templates */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">快速开始</span>
          <span className="text-xs text-muted-foreground">选择一个工作流模板</span>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {WORKFLOW_TEMPLATES.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={formLocked}
              onClick={() => {
                if (formLocked) return;
                setInputText(t.prompt);
                setSelectedModules(t.modules);
                setSelectedSuggestion(null);
              }}
              className={`flex flex-col gap-1 rounded-lg border bg-card p-3 text-left transition-all shadow-sm hover:border-primary/40 hover:shadow-md disabled:opacity-50 disabled:pointer-events-none
                ${inputText === t.prompt ? 'border-primary bg-accent/50' : 'border-border'}`}
            >
              <div className="flex items-center gap-1.5">
                <span className="text-base">{t.icon}</span>
                <span className="text-xs font-medium text-foreground">{t.label}</span>
              </div>
              <p className="text-[11px] text-muted-foreground leading-relaxed">{t.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Steps */}
      <div className="flex items-center gap-0">
        {['发布任务', '选择团队', '执行中'].map((label, i) => (
          <div key={label} className="flex items-center flex-1">
            <div className="flex items-center gap-2">
              <div className={`flex h-6 w-6 items-center justify-center rounded-full text-sm font-medium
                ${stepStates[i] === 2 ? 'bg-primary text-primary-foreground' :
                  stepStates[i] === 1 ? 'border-2 border-primary text-primary' :
                  'border border-border text-muted-foreground'}`}>
                {stepStates[i] === 2 ? <Check className="h-3 w-3" /> : i + 1}
              </div>
              <span className={`text-sm ${stepStates[i] > 0 ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>{label}</span>
            </div>
            {i < 2 && <div className={`flex-1 h-px mx-3 ${stepStates[i + 1] >= 1 ? 'bg-primary' : 'bg-border'}`} />}
          </div>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <X className="h-4 w-4 shrink-0" />{error}
        </div>
      )}

      {/* Input Section */}
      <div className="rounded-lg border border-border bg-card shadow-sm">
        <div className="p-4 space-y-4">
          {/* Textarea */}
          <textarea
            className="w-full min-h-[100px] resize-none rounded-md border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary disabled:opacity-50 transition-colors"
            placeholder="例如：分析本月经营数据，识别收入波动、成本压力，并给出下周管理动作建议。"
            value={inputText}
            maxLength={5000}
            disabled={formLocked}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !loading && step !== 'running' && step !== 'done') handleSubmit();
            }}
          />

          {/* File upload */}
          <div
            className={`flex items-center gap-3 rounded-md border border-dashed px-3 py-3 transition-colors
              ${formLocked ? 'cursor-not-allowed opacity-50' : 'cursor-pointer hover:bg-secondary'}
              ${file ? 'border-primary/40 bg-accent/50' : 'border-border bg-card'}`}
            onClick={() => !formLocked && fileInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); if (!formLocked && e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); }}
          >
            {file ? <FileText className="h-4 w-4 text-primary shrink-0" /> : <Upload className="h-4 w-4 text-muted-foreground shrink-0" />}
            <div className="flex-1 min-w-0">
              <div className="text-sm text-foreground">{file ? file.name : '点击或拖拽上传附件'}</div>
              <div className="text-[11px] text-muted-foreground">{file ? '附件已就绪' : '支持 CSV、TXT、Markdown'}</div>
            </div>
            {file && !formLocked && (
              <button type="button" onClick={(e) => { e.stopPropagation(); setFile(null); }} className="text-muted-foreground hover:text-foreground">
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <input ref={fileInputRef} type="file" className="hidden" onChange={(e) => { if (e.target.files?.[0]) setFile(e.target.files[0]); }} />
        </div>

        {/* Divider */}
        <div className="border-t border-border" />

        {/* Team selection */}
        <div className="p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-foreground">选择你的团队成员</h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">不指定成员时由 AI 自动组队</p>
            </div>
            <span className="rounded bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground">可选</span>
          </div>

          {/* AI plan */}
          {step === 'confirm' && plan && (
            <div className="rounded-xl border border-border bg-muted/30 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                <span className="text-sm font-medium">AI 规划方案 · {plan.task_type_label}</span>
                <span className="ml-auto text-xs text-muted-foreground">可直接编辑修改</span>
              </div>

              <p className="text-xs text-muted-foreground border-l-2 border-primary/40 pl-3 italic">
                {plan.reasoning}
              </p>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-foreground/70">
                  补充指令 / 修改分析方向（可选）
                </label>
                <textarea
                  className="w-full min-h-[80px] rounded-lg border border-border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary/30 placeholder:text-muted-foreground/50"
                  placeholder="例如：重点关注 Q3 数据，忽略节假日因素；或「只分析移动端用户」..."
                  value={userInstructions}
                  onChange={e => setUserInstructions(e.target.value)}
                  rows={3}
                />
              </div>
            </div>
          )}

          {/* Presets */}
          <div className="flex flex-wrap gap-1.5">
            {PRESET_COMBOS.map((c) => (
              <button key={c.label} type="button" disabled={selectionLocked}
                onClick={() => setSelectedModules(c.modules)}
                className={`rounded-md px-3 py-1 text-xs transition-colors
                  ${isSameSelection(selectedModules, c.modules) ? 'bg-primary text-primary-foreground' : 'bg-secondary text-secondary-foreground hover:bg-secondary'}
                  disabled:opacity-50`}
              >{c.label}</button>
            ))}
          </div>

          {/* Agent grid */}
          <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
            {agents.map((a) => (
              <ModuleCard key={a.id} agent={a} selected={selectedModules.includes(a.id)} onToggle={toggleModule} disabled={selectionLocked} />
            ))}
          </div>
        </div>

        {/* Action bar */}
        <div className="flex items-center justify-between border-t border-border bg-card px-4 py-3">
          <div className="text-xs text-muted-foreground">
            {selectedModules.length > 0 ? `已选择 ${selectedModules.length} 名成员` : '未指定成员，AI 将自动组队'}
          </div>
          <div className="flex items-center gap-2">
            {step === 'running' && (
              <Button variant="outline" onClick={handleCancel} disabled={cancelling}>
                {cancelling ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 取消中</> : '取消任务'}
              </Button>
            )}
            <Button
              onClick={step === 'confirm' ? handleConfirm : handleSubmit}
              disabled={loading || step === 'running' || step === 'done' || (step === 'confirm' && selectedModules.length === 0)}
            >
              {loading && step === 'planning' ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> AI 组队中</> :
               loading && step === 'running' ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> 执行中</> :
               <>下达指令 <ArrowRight className="h-3.5 w-3.5" /></>}
            </Button>
          </div>
        </div>
      </div>

      {/* Execution */}
      {(step === 'running' || step === 'done') && (
        <div className="space-y-4 rounded-lg border border-border bg-card p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-foreground">{step === 'done' ? '执行完成' : '执行中'}</h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                {step === 'done' ? '所有模块已返回结果' : '正在执行，实时同步日志'}
              </p>
            </div>
            <span className="text-xs text-muted-foreground">{progressValue}%</span>
          </div>
          <Progress value={progressValue} className="h-1" />
          <ExecutionTimeline events={events} status={step === 'done' ? 'done' : 'running'} />

          {step === 'done' && taskId && (
            <div className="flex items-center justify-between rounded-md bg-accent px-4 py-3">
              <div>
                <div className="text-sm font-medium text-foreground">任务已完成</div>
                <p className="text-xs text-muted-foreground">可以查看完整报告并发布到飞书</p>
              </div>
              <Button onClick={() => navigate(`/results/${taskId}`)}>
                查看报告 <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
