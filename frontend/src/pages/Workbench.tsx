import { useState, useEffect, useRef } from 'react';
import {
  submitTask, confirmTask, listAgents, createSSEConnection, getTaskStatus,
} from '../services/api';
import type { AgentInfo, SSEEvent, TaskPlanResponse } from '../services/types';
import ModuleCard from '../components/ModuleCard';
import ExecutionTimeline from '../components/ExecutionTimeline';
import { useNavigate } from 'react-router-dom';

const PRESET_COMBOS = [
  { label: '经营分析', modules: ['data_analyst', 'finance_advisor', 'ceo_assistant'] },
  { label: '立项评估', modules: ['product_manager', 'finance_advisor', 'ceo_assistant'] },
  { label: '内容增长', modules: ['seo_advisor', 'content_manager', 'operations_manager'] },
  { label: '综合分析', modules: ['data_analyst', 'operations_manager', 'ceo_assistant'] },
];

type Step = 'input' | 'planning' | 'confirm' | 'running' | 'done';

export default function Workbench() {
  const navigate = useNavigate();
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
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { listAgents().then(setAgents).catch(console.error); }, []);

  const toggleModule = (id: string) => {
    setSelectedModules((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]
    );
  };

  const handleSubmit = async () => {
    if (!inputText.trim() && !file) {
      setError('请输入任务描述或上传文件');
      return;
    }
    setError(null);
    setLoading(true);
    setStep('planning');
    try {
      const result = await submitTask(inputText, file ?? undefined);
      setPlan(result);
      setTaskId(result.task_id);
      setSelectedModules(result.selected_modules);
      setStep('confirm');
    } catch {
      setError('任务识别失败，请重试');
      setStep('input');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!taskId || selectedModules.length === 0) {
      setError('请至少选择一个分析模块');
      return;
    }
    setError(null);
    setLoading(true);
    setStep('running');
    setEvents([]);
    try {
      await confirmTask(taskId, selectedModules);
      const es = createSSEConnection(taskId);
      es.onmessage = (e) => {
        const data = JSON.parse(e.data) as SSEEvent & { status?: string };
        if (data.event_type === 'stream.end') {
          es.close();
          setStep('done');
          setLoading(false);
        } else if (data.event_type !== 'stream.timeout') {
          setEvents((prev) => [...prev, data as SSEEvent]);
        }
      };
      es.onerror = async () => {
        es.close();
        if (taskId) {
          try {
            const statusData = await getTaskStatus(taskId);
            const s = (statusData as { status: string }).status;
            if (s === 'done') { setStep('done'); }
            else if (s === 'failed') { setStep('confirm'); setError('任务执行失败，请重新确认执行'); }
            else { setError('连接中断，请刷新页面查看进度'); }
          } catch {
            setStep('confirm');
            setError('连接中断，请刷新页面');
          }
        }
        setLoading(false);
      };
    } catch {
      setError('执行失败');
      setStep('confirm');
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'var(--space-8) var(--space-6)' }}>

      {/* Header */}
      <div style={{ marginBottom: 'var(--space-10)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' }}>
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: '0.15em', color: 'var(--accent)',
            textTransform: 'uppercase',
          }}>
            ◆ MISSION CONTROL
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>v1.0</span>
        </div>
        <h1 style={{
          fontSize: 28, fontWeight: 700, color: 'var(--text-primary)',
          letterSpacing: '-0.03em', lineHeight: 1.2, marginBottom: 8,
        }}>
          飞书 AI 工作台
        </h1>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          描述你的任务 → AI 自动识别类型 → 调用分析模块 → 结果同步飞书
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          marginBottom: 'var(--space-4)',
          padding: 'var(--space-3) var(--space-4)',
          background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)',
          borderRadius: 'var(--radius)',
          fontSize: 12, color: 'var(--error)',
          display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
        }}>
          <span>✗</span> {error}
          <button
            className="btn btn-ghost btn-sm"
            style={{ marginLeft: 'auto', color: 'var(--error)', padding: '2px 6px', fontSize: 10 }}
            onClick={() => setError(null)}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── STEP 01: Input ── */}
      <section style={{
        marginBottom: 'var(--space-4)',
        opacity: step === 'input' || step === 'planning' ? 1 : 0.6,
        transition: 'opacity 0.3s',
      }}>
        <div className="card" style={{ padding: 'var(--space-5)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '3px 8px',
              background: step === 'input' || step === 'planning' ? 'var(--accent-dim)' : 'var(--bg-elevated)',
              color: step === 'input' || step === 'planning' ? 'var(--accent)' : 'var(--text-muted)',
              border: `1px solid ${step === 'input' || step === 'planning' ? 'rgba(163,255,0,0.25)' : 'var(--border)'}`,
              borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
            }}>
              01
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>描述任务</span>
          </div>

          <textarea
            rows={4}
            className="input"
            placeholder="例如：分析本月经营数据，重点看收入趋势和成本风险..."
            value={inputText}
            disabled={step !== 'input'}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && step === 'input') handleSubmit();
            }}
            style={{ marginBottom: 'var(--space-3)', minHeight: 100 }}
          />

          {/* File upload */}
          <div
            style={{
              padding: 'var(--space-4)',
              border: `1px dashed ${file ? 'rgba(163,255,0,0.4)' : 'var(--border)'}`,
              borderRadius: 'var(--radius)',
              background: file ? 'var(--accent-dim)' : 'transparent',
              cursor: step !== 'input' ? 'not-allowed' : 'pointer',
              textAlign: 'center',
              transition: 'all 0.15s',
              marginBottom: 'var(--space-4)',
            }}
            onClick={() => step === 'input' && fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); }}
            onDrop={(e) => {
              e.preventDefault();
              if (step !== 'input') return;
              const dropped = e.dataTransfer.files[0];
              if (dropped && (dropped.name.endsWith('.csv') || dropped.name.endsWith('.txt'))) {
                setFile(dropped);
              }
            }}
          >
            {file ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, color: 'var(--accent)' }}>📎 {file.name}</span>
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ color: 'var(--text-muted)', padding: '1px 4px', fontSize: 10 }}
                  onClick={(e) => { e.stopPropagation(); setFile(null); }}
                >✕</button>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  拖拽或点击上传数据文件
                </p>
                <p style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>CSV · TXT</p>
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.txt"
            style={{ display: 'none' }}
            onChange={(e) => { if (e.target.files?.[0]) setFile(e.target.files[0]); }}
          />

          <button
            className="btn btn-accent btn-lg btn-block"
            disabled={step !== 'input' || loading}
            onClick={handleSubmit}
          >
            {loading && step === 'planning' ? (
              <><div className="spinner" style={{ borderTopColor: '#000', borderColor: 'rgba(0,0,0,0.2)' }} /> 识别中...</>
            ) : (
              <>⚡ 识别任务 <span style={{ opacity: 0.6, fontSize: 10 }}>⌘↵</span></>
            )}
          </button>
        </div>
      </section>

      {/* ── STEP 02: Confirm modules ── */}
      {(step === 'confirm' || step === 'running' || step === 'done') && plan && (
        <section style={{ marginBottom: 'var(--space-4)', animation: 'fade-in-up 0.25s ease both' }}>
          <div className="card" style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '3px 8px',
                background: step === 'confirm' ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                color: step === 'confirm' ? 'var(--accent)' : 'var(--text-muted)',
                border: `1px solid ${step === 'confirm' ? 'rgba(163,255,0,0.25)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
              }}>
                02
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>选择分析模块</span>
              <span style={{
                marginLeft: 'auto', fontSize: 9, fontWeight: 700, padding: '2px 8px',
                background: 'rgba(129,140,248,0.12)', color: 'var(--info)',
                border: '1px solid rgba(129,140,248,0.2)',
                borderRadius: 'var(--radius-sm)', letterSpacing: '0.08em',
              }}>
                {plan.task_type_label}
              </span>
            </div>

            {/* Reasoning */}
            <p style={{
              fontSize: 11, color: 'var(--text-secondary)', padding: 'var(--space-3) var(--space-4)',
              background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              marginBottom: 'var(--space-4)', lineHeight: 1.6,
            }}>
              <span style={{ color: 'var(--text-muted)' }}>REASON /</span>{' '}{plan.reasoning}
            </p>

            {/* Preset combos */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>PRESET</span>
              {PRESET_COMBOS.map((c) => (
                <button
                  key={c.label}
                  className="btn btn-sm"
                  disabled={step !== 'confirm'}
                  onClick={() => setSelectedModules(c.modules)}
                  style={{
                    borderColor: JSON.stringify(selectedModules.sort()) === JSON.stringify([...c.modules].sort())
                      ? 'var(--accent)' : undefined,
                    color: JSON.stringify(selectedModules.sort()) === JSON.stringify([...c.modules].sort())
                      ? 'var(--accent)' : undefined,
                  }}
                >
                  {c.label}
                </button>
              ))}
            </div>

            {/* Agent grid */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 'var(--space-3)',
              marginBottom: 'var(--space-4)',
            }}>
              {agents.map((agent) => (
                <ModuleCard
                  key={agent.id}
                  agent={agent}
                  selected={selectedModules.includes(agent.id)}
                  onToggle={step === 'confirm' ? toggleModule : () => {}}
                  disabled={step !== 'confirm'}
                />
              ))}
            </div>

            <button
              className="btn btn-accent btn-lg btn-block"
              disabled={step !== 'confirm' || selectedModules.length === 0 || loading}
              onClick={handleConfirm}
            >
              {loading && step === 'running' ? (
                <><div className="spinner" style={{ borderTopColor: '#000', borderColor: 'rgba(0,0,0,0.2)' }} /> 执行中...</>
              ) : (
                <>▶ 确认执行 <span style={{ opacity: 0.7 }}>{selectedModules.length} 个模块</span></>
              )}
            </button>
          </div>
        </section>
      )}

      {/* ── STEP 03: Execution ── */}
      {(step === 'running' || step === 'done') && (
        <section style={{ marginBottom: 'var(--space-4)', animation: 'fade-in-up 0.25s ease both' }}>
          <div className="card" style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '3px 8px',
                background: step === 'done' ? 'rgba(52,211,153,0.12)' : 'rgba(251,146,60,0.12)',
                color: step === 'done' ? 'var(--success)' : 'var(--warning)',
                border: `1px solid ${step === 'done' ? 'rgba(52,211,153,0.25)' : 'rgba(251,146,60,0.25)'}`,
                borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
              }}>
                03
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>执行日志</span>
              {step === 'running' && (
                <div style={{
                  marginLeft: 'auto',
                  width: 120, height: 2,
                  background: 'var(--bg-elevated)',
                  borderRadius: 1, overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%',
                    background: 'linear-gradient(90deg, var(--accent), transparent)',
                    animation: 'progress-fill 3s ease-out infinite',
                    transformOrigin: 'left',
                  }} />
                </div>
              )}
            </div>

            <ExecutionTimeline events={events} status={step === 'running' ? 'running' : 'done'} />

            {step === 'done' && taskId && (
              <button
                className="btn btn-accent btn-lg"
                style={{ marginTop: 'var(--space-4)' }}
                onClick={() => navigate(`/results/${taskId}`)}
              >
                查看完整报告 →
              </button>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
