import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getTaskResults, publishTask } from '../services/api';
import type { TaskResultsResponse } from '../services/types';
import FeishuAssetCard from '../components/FeishuAssetCard';

const STATUS_META: Record<string, { label: string; color: string }> = {
  done:     { label: 'DONE',     color: 'var(--success)' },
  running:  { label: 'RUNNING',  color: 'var(--warning)' },
  failed:   { label: 'FAILED',   color: 'var(--error)'   },
  pending:  { label: 'PENDING',  color: 'var(--text-muted)' },
};

const PUBLISH_OPTIONS = [
  { value: 'doc',     label: '飞书文档',   desc: '完整分析报告' },
  { value: 'bitable', label: '多维表格',   desc: '行动建议清单' },
  { value: 'message', label: '群消息',     desc: '管理摘要推送' },
  { value: 'task',    label: '飞书任务',   desc: '行动项转任务' },
];

export default function ResultView() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<TaskResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [showPublish, setShowPublish] = useState(false);
  const [publishTypes, setPublishTypes] = useState<string[]>(['doc', 'task']);
  const [docTitle, setDocTitle] = useState('');
  const [chatId, setChatId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) return;
    getTaskResults(taskId)
      .then((d) => { setData(d); if (d.agent_results[0]) setExpandedAgent(d.agent_results[0].agent_id); })
      .catch(() => setError('加载结果失败'))
      .finally(() => setLoading(false));
  }, [taskId]);

  const handlePublish = async () => {
    if (!taskId) return;
    setPublishing(true);
    setError(null);
    try {
      await publishTask(taskId, publishTypes, {
        docTitle: docTitle || undefined,
        chatId: chatId || undefined,
      });
      const updated = await getTaskResults(taskId);
      setData(updated);
      setShowPublish(false);
    } catch {
      setError('发布失败，请检查飞书配置');
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 12 }}>
        <div className="spinner" />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>加载报告...</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ padding: 'var(--space-8) var(--space-6)', maxWidth: 860, margin: '0 auto' }}>
        <p style={{ fontSize: 13, color: 'var(--error)' }}>任务不存在</p>
        <button className="btn" style={{ marginTop: 'var(--space-4)' }} onClick={() => navigate('/')}>← 返回工作台</button>
      </div>
    );
  }

  const statusMeta = STATUS_META[data.status] || { label: data.status.toUpperCase(), color: 'var(--text-muted)' };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'var(--space-8) var(--space-6)' }}>

      {/* Back + header */}
      <div style={{ marginBottom: 'var(--space-8)' }}>
        <button
          className="btn btn-ghost btn-sm"
          style={{ marginBottom: 'var(--space-4)', color: 'var(--text-muted)' }}
          onClick={() => navigate('/')}
        >
          ← 返回工作台
        </button>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 6 }}>
              {data.task_type_label}报告
            </h1>
            <p style={{ fontSize: 11, color: 'var(--text-muted)' }}>TASK / {taskId}</p>
          </div>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '4px 10px',
            background: `${statusMeta.color}18`, color: statusMeta.color,
            border: `1px solid ${statusMeta.color}30`,
            borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
            alignSelf: 'flex-start',
          }}>
            {statusMeta.label}
          </span>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          marginBottom: 'var(--space-4)', padding: 'var(--space-3) var(--space-4)',
          background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)',
          borderRadius: 'var(--radius)', fontSize: 12, color: 'var(--error)',
        }}>
          ✗ {error}
        </div>
      )}

      {/* Summary card */}
      {data.result_summary && (
        <div
          className="card"
          style={{
            padding: 'var(--space-5)', marginBottom: 'var(--space-4)',
            borderColor: 'rgba(163,255,0,0.15)',
            background: 'rgba(163,255,0,0.04)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.15em' }}>◆ EXECUTIVE SUMMARY</span>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.7 }}>
            {data.result_summary}
          </p>
        </div>
      )}

      {/* Agent results accordion */}
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.15em', marginBottom: 'var(--space-3)', textTransform: 'uppercase' }}>
          分析模块报告 ({data.agent_results.length})
        </div>

        {data.agent_results.map((r, ri) => {
          const expanded = expandedAgent === r.agent_id;
          return (
            <div
              key={r.agent_id}
              className="card"
              style={{
                marginBottom: 'var(--space-2)',
                overflow: 'hidden',
                borderColor: expanded ? 'var(--border-bright)' : 'var(--border)',
                animation: `fade-in-up 0.2s ease both`,
                animationDelay: `${ri * 60}ms`,
              }}
            >
              {/* Accordion header */}
              <button
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                  padding: 'var(--space-4) var(--space-5)',
                  background: 'none', border: 'none', cursor: 'pointer',
                  textAlign: 'left',
                  borderBottom: expanded ? '1px solid var(--border)' : 'none',
                  color: 'var(--text-primary)',
                  fontFamily: 'var(--font)',
                }}
                onClick={() => setExpandedAgent(expanded ? null : r.agent_id)}
              >
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: '2px 6px',
                  background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
                  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                  letterSpacing: '0.08em', flexShrink: 0,
                }}>
                  {r.agent_name}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', flex: 1 }}>
                  {r.sections.length} 个分析板块
                  {r.action_items.length > 0 && ` · ${r.action_items.length} 项行动建议`}
                </span>
                <span style={{
                  fontSize: 11, color: 'var(--text-muted)',
                  transform: expanded ? 'rotate(180deg)' : 'none',
                  transition: 'transform 0.2s',
                }}>▼</span>
              </button>

              {/* Accordion content */}
              {expanded && (
                <div style={{ padding: 'var(--space-5)' }}>
                  {r.sections.map((s, i) => (
                    <div key={i} style={{ marginBottom: 'var(--space-5)' }}>
                      <div style={{
                        fontSize: 11, fontWeight: 700, color: 'var(--text-primary)',
                        marginBottom: 'var(--space-2)', paddingBottom: 'var(--space-2)',
                        borderBottom: '1px solid var(--border)',
                      }}>
                        {s.title}
                      </div>
                      <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8, whiteSpace: 'pre-line' }}>
                        {s.content}
                      </p>
                    </div>
                  ))}

                  {r.action_items.length > 0 && (
                    <div>
                      <div style={{
                        fontSize: 10, fontWeight: 700, color: 'var(--accent)',
                        letterSpacing: '0.1em', marginBottom: 'var(--space-3)',
                      }}>
                        ACTION ITEMS
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                        {r.action_items.map((item, i) => (
                          <div key={i} style={{
                            display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)',
                            fontSize: 12, color: 'var(--text-primary)',
                          }}>
                            <span style={{
                              flexShrink: 0, width: 18, height: 18,
                              border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              fontSize: 9, color: 'var(--text-muted)', fontWeight: 700, marginTop: 2,
                            }}>
                              {String(i + 1).padStart(2, '0')}
                            </span>
                            <span style={{ lineHeight: 1.6 }}>{item}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Published assets */}
      {data.published_assets.length > 0 && (
        <div className="card" style={{ marginBottom: 'var(--space-4)', overflow: 'hidden' }}>
          <div style={{
            padding: 'var(--space-3) var(--space-4)',
            borderBottom: '1px solid var(--border)',
            fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.15em',
          }}>
            已同步到飞书
          </div>
          {data.published_assets.map((asset, i) => (
            <FeishuAssetCard key={i} asset={asset} />
          ))}
        </div>
      )}

      {/* Publish to Feishu */}
      {data.status === 'done' && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          {!showPublish ? (
            <button className="btn btn-accent btn-lg btn-block" onClick={() => setShowPublish(true)}>
              ↗ 同步到飞书
            </button>
          ) : (
            <div className="card" style={{ padding: 'var(--space-5)' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.15em', marginBottom: 'var(--space-4)' }}>
                选择同步内容
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
                {PUBLISH_OPTIONS.map((opt) => {
                  const checked = publishTypes.includes(opt.value);
                  return (
                    <div
                      key={opt.value}
                      role="checkbox"
                      aria-checked={checked}
                      onClick={() => setPublishTypes((prev) =>
                        prev.includes(opt.value) ? prev.filter((v) => v !== opt.value) : [...prev, opt.value]
                      )}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                        padding: 'var(--space-3) var(--space-4)',
                        background: checked ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                        border: `1px solid ${checked ? 'rgba(163,255,0,0.25)' : 'var(--border)'}`,
                        borderRadius: 'var(--radius)', cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      <div style={{
                        width: 14, height: 14, flexShrink: 0,
                        border: `1.5px solid ${checked ? 'var(--accent)' : 'var(--border-bright)'}`,
                        borderRadius: 'var(--radius-sm)', background: checked ? 'var(--accent)' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {checked && <svg width="8" height="6" viewBox="0 0 8 6" fill="none"><path d="M1 3L3 5L7 1" stroke="#000" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                      </div>
                      <div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: checked ? 'var(--accent)' : 'var(--text-primary)', fontFamily: 'var(--font)' }}>{opt.label}</div>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{opt.desc}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <input
                className="input"
                placeholder="文档标题（可选）"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                style={{ marginBottom: 'var(--space-2)' }}
              />
              <input
                className="input"
                placeholder="群 ID（可选，默认使用配置的群）"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                style={{ marginBottom: 'var(--space-4)' }}
              />

              <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
                <button
                  className="btn btn-accent btn-lg"
                  style={{ flex: 1, justifyContent: 'center' }}
                  disabled={publishing || publishTypes.length === 0}
                  onClick={handlePublish}
                >
                  {publishing ? <><div className="spinner" style={{ borderTopColor: '#000', borderColor: 'rgba(0,0,0,0.2)' }} />同步中...</> : '↗ 确认同步'}
                </button>
                <button
                  className="btn"
                  onClick={() => setShowPublish(false)}
                  disabled={publishing}
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
