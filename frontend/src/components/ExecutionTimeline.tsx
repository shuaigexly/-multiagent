import { useEffect, useRef } from 'react';
import type { SSEEvent } from '../services/types';

interface Props {
  events: SSEEvent[];
  status: 'running' | 'done' | 'failed' | 'idle';
}

const EVENT_COLOR: Record<string, string> = {
  'task.recognized': 'var(--info)',
  'context.retrieved': 'var(--info)',
  'module.started': 'var(--warning)',
  'module.completed': 'var(--success)',
  'module.failed': 'var(--error)',
  'feishu.writing': '#c084fc',
  'task.done': 'var(--accent)',
  'task.error': 'var(--error)',
};

const EVENT_PREFIX: Record<string, string> = {
  'task.recognized': 'PLAN',
  'context.retrieved': 'CTX',
  'module.started': 'RUN',
  'module.completed': 'DONE',
  'module.failed': 'ERR',
  'feishu.writing': 'SYNC',
  'task.done': 'FIN',
  'task.error': 'ERR',
};

function LogLine({ event, index }: { event: SSEEvent; index: number }) {
  const color = EVENT_COLOR[event.event_type] || 'var(--text-secondary)';
  const prefix =
    EVENT_PREFIX[event.event_type] ||
    event.event_type.split('.').pop()?.toUpperCase() ||
    'LOG';
  const isSuccess = event.event_type === 'task.done';
  const isError =
    event.event_type === 'task.error' || event.event_type === 'module.failed';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-3)',
        padding: 'var(--space-2) 0',
        borderBottom: '1px solid var(--border)',
        animation: 'fade-in 0.2s ease both',
        animationDelay: `${Math.min(index * 30, 200)}ms`,
      }}
    >
      <span
        style={{
          fontSize: 10,
          color: 'var(--text-muted)',
          flexShrink: 0,
          width: 24,
          textAlign: 'right',
          paddingTop: 1,
        }}
      >
        {String(event.sequence).padStart(2, '0')}
      </span>
      <div
        style={{
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          paddingTop: 5,
          gap: 2,
        }}
      >
        <div
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            flexShrink: 0,
            background: isSuccess ? 'var(--accent)' : isError ? 'var(--error)' : color,
            boxShadow: isSuccess ? '0 0 8px var(--accent)' : undefined,
          }}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
            marginBottom: 2,
          }}
        >
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: '1px 5px',
              background: `${color}18`,
              color,
              border: `1px solid ${color}30`,
              borderRadius: 'var(--radius-sm)',
              letterSpacing: '0.08em',
              flexShrink: 0,
            }}
          >
            {prefix}
          </span>
          {event.agent_name && (
            <span
              style={{
                fontSize: 10,
                color: 'var(--text-muted)',
                flexShrink: 0,
              }}
            >
              [{event.agent_name}]
            </span>
          )}
        </div>
        <p
          style={{
            fontSize: 12,
            color: isSuccess
              ? 'var(--accent)'
              : isError
                ? 'var(--error)'
                : 'var(--text-primary)',
            lineHeight: 1.5,
            wordBreak: 'break-word',
          }}
        >
          {event.message}
        </p>
      </div>
    </div>
  );
}

export default function ExecutionTimeline({ events, status }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [events.length]);

  if (events.length === 0 && status === 'idle') return null;

  return (
    <div
      style={{
        background: 'var(--bg-base)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
          padding: 'var(--space-2) var(--space-4)',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-surface)',
        }}
      >
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--error)' }} />
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--warning)' }} />
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--success)' }} />
        <span
          style={{
            fontSize: 10,
            color: 'var(--text-muted)',
            marginLeft: 'var(--space-2)',
            letterSpacing: '0.05em',
          }}
        >
          EXECUTION LOG
        </span>
        {status === 'running' && (
          <div
            style={{
              marginLeft: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <div className="spinner" />
            <span style={{ fontSize: 10, color: 'var(--warning)' }}>RUNNING</span>
          </div>
        )}
        {status === 'done' && (
          <span
            style={{
              marginLeft: 'auto',
              fontSize: 10,
              color: 'var(--accent)',
              letterSpacing: '0.05em',
            }}
          >
            ✓ COMPLETE
          </span>
        )}
        {status === 'failed' && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--error)' }}>
            ✗ FAILED
          </span>
        )}
      </div>
      <div
        style={{
          padding: 'var(--space-2) var(--space-4)',
          maxHeight: 360,
          overflowY: 'auto',
          fontFamily: 'var(--font)',
        }}
      >
        {events.length === 0 ? (
          <div
            style={{
              padding: 'var(--space-4) 0',
              color: 'var(--text-muted)',
              fontSize: 11,
            }}
          >
            <span style={{ animation: 'blink 1s step-end infinite' }}>▊</span> 等待执行...
          </div>
        ) : (
          events.map((event, index) => (
            <LogLine key={event.sequence} event={event} index={index} />
          ))
        )}
        {status === 'running' && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: 'var(--space-2) 0',
            }}
          >
            <div className="spinner" style={{ width: 10, height: 10 }} />
            <span
              style={{
                fontSize: 11,
                color: 'var(--text-muted)',
                animation: 'blink 1.2s step-end infinite',
              }}
            >
              处理中...
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
