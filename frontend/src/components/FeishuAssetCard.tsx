import { ExternalLink, FileText, BarChart3, MessageSquare, CheckSquare, BookOpen, Paperclip, Presentation } from 'lucide-react';
import { getSafeExternalUrl } from '../lib/safeUrl';
import type { PublishedAsset } from '../services/types';

interface Props { asset: PublishedAsset; }

const ASSET_META: Record<string, { label: string; icon: typeof FileText }> = {
  doc: { label: '文档', icon: FileText },
  bitable: { label: '多维表格', icon: BarChart3 },
  slides: { label: '演示文稿', icon: Presentation },
  message: { label: '消息', icon: MessageSquare },
  task: { label: '任务', icon: CheckSquare },
  wiki: { label: '知识库', icon: BookOpen },
};

export default function FeishuAssetCard({ asset }: Props) {
  const meta = ASSET_META[asset.type] ?? { label: asset.type, icon: Paperclip };
  const Icon = meta.icon;
  const safeUrl = getSafeExternalUrl(asset.url);
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2.5 hover:bg-secondary/50 transition-colors">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-accent text-accent-foreground">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-muted-foreground">{meta.label}</div>
        <div className="text-sm text-foreground truncate">{asset.title || asset.type}</div>
      </div>
      {safeUrl && (
        <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline flex items-center gap-1">
          打开 <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  );
}
