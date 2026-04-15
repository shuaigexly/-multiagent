import type { PublishedAsset } from '../services/types';

interface Props {
  asset: PublishedAsset;
}

const ASSET_META: Record<string, { label: string; color: string; icon: string }> = {
  doc: { label: '飞书文档', color: 'var(--info)', icon: '📄' },
  bitable: { label: '多维表格', color: 'var(--success)', icon: '📊' },
  message: { label: '群消息', color: 'var(--warning)', icon: '💬' },
  task: { label: '飞书任务', color: '#c084fc', icon: '✓' },
  wiki: { label: '知识库', color: 'var(--gold)', icon: '📚' },
};

export default function FeishuAssetCard({ asset }: Props) {
  const meta = ASSET_META[asset.type] || {
    label: asset.type,
    color: 'var(--text-secondary)',
    icon: '📎',
  };

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: 'var(--space-3) var(--space-4)',
        borderBottom: '1px solid var(--border)',
        animation: 'fade-in 0.2s ease both',
      }}
    >
      <span
        style={{
          fontSize: 13,
          flexShrink: 0,
          width: 28,
          textAlign: 'center',
        }}
      >
        {meta.icon}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              padding: '1px 5px',
              background: `${meta.color}18`,
              color: meta.color,
              border: `1px solid ${meta.color}30`,
              borderRadius: 'var(--radius-sm)',
              letterSpacing: '0.08em',
            }}
          >
            {meta.label}
          </span>
        </div>
        <p
          style={{
            fontSize: 12,
            color: 'var(--text-primary)',
            marginTop: 2,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {asset.title || asset.type}
        </p>
      </div>

      {asset.url && (
        <a
          href={asset.url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-sm"
          style={{ flexShrink: 0, textDecoration: 'none' }}
        >
          打开 ↗
        </a>
      )}
    </div>
  );
}
