import type { AgentInfo } from '../services/types';

interface Props {
  agent: AgentInfo;
  selected: boolean;
  onToggle: (id: string) => void;
  disabled?: boolean;
}

const MODULE_ACCENT: Record<string, string> = {
  data_analyst: 'var(--info)',
  finance_advisor: 'var(--success)',
  seo_advisor: 'var(--warning)',
  content_manager: '#c084fc',
  product_manager: '#22d3ee',
  operations_manager: 'var(--error)',
  ceo_assistant: 'var(--gold)',
};

const MODULE_PREFIX: Record<string, string> = {
  data_analyst: 'DA',
  finance_advisor: 'FIN',
  seo_advisor: 'SEO',
  content_manager: 'CM',
  product_manager: 'PM',
  operations_manager: 'OPS',
  ceo_assistant: 'CEO',
};

export default function ModuleCard({ agent, selected, onToggle, disabled }: Props) {
  const accent = MODULE_ACCENT[agent.id] || 'var(--text-secondary)';
  const prefix = MODULE_PREFIX[agent.id] || agent.id.slice(0, 3).toUpperCase();

  return (
    <div
      role="checkbox"
      aria-checked={selected}
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && onToggle(agent.id)}
      onKeyDown={(e) => {
        if ((e.key === ' ' || e.key === 'Enter') && !disabled) {
          e.preventDefault();
          onToggle(agent.id);
        }
      }}
      style={{
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        background: selected ? 'var(--bg-elevated)' : 'var(--bg-surface)',
        border: `1px solid ${selected ? accent : 'var(--border)'}`,
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-4)',
        transition: 'all 0.15s ease',
        position: 'relative',
        overflow: 'hidden',
        boxShadow: selected
          ? `0 0 0 1px ${accent}20, inset 0 0 0 1px ${accent}10`
          : 'var(--shadow-card)',
        animation: 'fade-in-up 0.2s ease both',
      }}
      onMouseEnter={(e) => {
        if (!disabled && !selected) {
          e.currentTarget.style.borderColor = 'var(--border-bright)';
          e.currentTarget.style.background = 'var(--bg-elevated)';
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled && !selected) {
          e.currentTarget.style.borderColor = 'var(--border)';
          e.currentTarget.style.background = 'var(--bg-surface)';
        }
      }}
    >
      {selected && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 2,
            background: accent,
            borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
          }}
        />
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          marginBottom: 'var(--space-3)',
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            flexShrink: 0,
            background: `${accent}18`,
            border: `1px solid ${accent}30`,
            borderRadius: 'var(--radius)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 10,
            fontWeight: 700,
            color: accent,
            letterSpacing: '0.05em',
          }}
        >
          {prefix}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: 'var(--text-primary)',
              letterSpacing: '-0.01em',
            }}
          >
            {agent.name}
          </div>
        </div>

        <div
          style={{
            width: 14,
            height: 14,
            flexShrink: 0,
            border: `1.5px solid ${selected ? accent : 'var(--border-bright)'}`,
            borderRadius: 'var(--radius-sm)',
            background: selected ? accent : 'transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.15s',
          }}
        >
          {selected && (
            <svg width="8" height="6" viewBox="0 0 8 6" fill="none" aria-hidden="true">
              <path
                d="M1 3L3 5L7 1"
                stroke="#000"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          )}
        </div>
      </div>

      <p
        style={{
          fontSize: 11,
          color: 'var(--text-secondary)',
          lineHeight: 1.5,
          margin: 0,
          marginBottom: 'var(--space-3)',
        }}
      >
        {agent.description}
      </p>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {agent.suitable_for.slice(0, 3).map((tag) => (
          <span
            key={tag}
            style={{
              fontSize: 10,
              padding: '1px 6px',
              background: 'var(--bg-base)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-muted)',
              letterSpacing: '0.03em',
            }}
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}
