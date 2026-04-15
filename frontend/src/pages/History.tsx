import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listTasks } from '../services/api';
import type { TaskListItem } from '../services/types';

const STATUS_META: Record<string, { label: string; color: string }> = {
  done: { label: 'DONE', color: 'var(--success)' },
  running: { label: 'RUNNING', color: 'var(--warning)' },
  failed: { label: 'FAILED', color: 'var(--error)' },
  pending: { label: 'PENDING', color: 'var(--text-muted)' },
  planning: { label: 'PLANNING', color: 'var(--info)' },
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function History() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTasks()
      .then(setTasks)
      .catch(() => setError('加载历史记录失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'var(--space-8) var(--space-6)' }}>
      {/* Header */}
      <div style={{ marginBottom: 'var(--space-8)' }}>
        <div
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '0.15em',
            color: 'var(--accent)',
            marginBottom: 'var(--space-2)',
          }}
        >
          ◆ MISSION HISTORY
        </div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.03em' }}>历史任务</h1>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 'var(--space-4) 0' }}>
          <div className="spinner" />
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>加载中...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            padding: 'var(--space-3) var(--space-4)',
            background: 'rgba(248,113,113,0.08)',
            border: '1px solid rgba(248,113,113,0.2)',
            borderRadius: 'var(--radius)',
            fontSize: 12,
            color: 'var(--error)',
            marginBottom: 'var(--space-4)',
          }}
        >
          ✗ {error}
        </div>
      )}

      {/* Table header */}
      {!loading && tasks.length > 0 && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '80px 1fr 100px 80px',
            gap: 'var(--space-4)',
            padding: 'var(--space-2) var(--space-4)',
            marginBottom: 'var(--space-1)',
          }}
        >
          {['STATUS', '任务描述', '时间', ''].map((h) => (
            <span
              key={h}
              style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.1em' }}
            >
              {h}
            </span>
          ))}
        </div>
      )}

      {/* Task rows */}
      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          {tasks.length === 0 ? (
            <div style={{ padding: 'var(--space-12) var(--space-4)', textAlign: 'center' }}>
              <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>暂无历史任务</p>
              <button className="btn btn-accent" style={{ marginTop: 'var(--space-4)' }} onClick={() => navigate('/')}>
                创建首个任务
              </button>
            </div>
          ) : (
            tasks.map((task, i) => {
              const meta = STATUS_META[task.status] || {
                label: task.status.toUpperCase(),
                color: 'var(--text-muted)',
              };
              const canView = task.status !== 'planning' && task.status !== 'pending';

              return (
                <div
                  key={task.id}
                  className="card"
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '80px 1fr 100px 80px',
                    gap: 'var(--space-4)',
                    padding: 'var(--space-3) var(--space-4)',
                    alignItems: 'center',
                    animation: 'fade-in-up 0.2s ease both',
                    animationDelay: `${Math.min(i * 40, 300)}ms`,
                    cursor: canView ? 'pointer' : 'default',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                  onClick={() => canView && navigate(`/results/${task.id}`)}
                  onMouseEnter={(e) => {
                    if (canView) {
                      (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-bright)';
                      (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.borderColor = '';
                    (e.currentTarget as HTMLElement).style.background = '';
                  }}
                >
                  {/* Status */}
                  <span
                    style={{
                      fontSize: 9,
                      fontWeight: 700,
                      padding: '2px 6px',
                      background: `${meta.color}18`,
                      color: meta.color,
                      border: `1px solid ${meta.color}30`,
                      borderRadius: 'var(--radius-sm)',
                      letterSpacing: '0.08em',
                      display: 'inline-block',
                      ...(task.status === 'running' ? { animation: 'glow-pulse 2s ease-in-out infinite' } : {}),
                    }}
                  >
                    {meta.label}
                  </span>

                  {/* Description */}
                  <div>
                    {task.task_type_label && (
                      <span
                        style={{
                          fontSize: 9,
                          fontWeight: 700,
                          padding: '1px 5px',
                          marginRight: 8,
                          background: 'rgba(129,140,248,0.12)',
                          color: 'var(--info)',
                          border: '1px solid rgba(129,140,248,0.2)',
                          borderRadius: 'var(--radius-sm)',
                          letterSpacing: '0.06em',
                        }}
                      >
                        {task.task_type_label}
                      </span>
                    )}
                    <span
                      style={{
                        fontSize: 12,
                        color: 'var(--text-secondary)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        display: 'inline',
                      }}
                    >
                      {task.input_text || '（文件上传）'}
                    </span>
                  </div>

                  {/* Time */}
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{formatDate(task.created_at)}</span>

                  {/* Action */}
                  <div>
                    {canView && <span style={{ fontSize: 11, color: 'var(--accent)' }}>查看 →</span>}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
