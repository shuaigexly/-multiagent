import { FileText, CalendarDays, CheckSquare, MessageSquare, Loader2, Sparkles } from 'lucide-react';

export interface Suggestion {
  id: string;
  type: 'doc' | 'calendar' | 'task' | 'chat';
  source: string;
  label: string;
  prompt: string;
  agents: string[];
}

interface Props {
  suggestions: Suggestion[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (s: Suggestion) => void;
  disabled?: boolean;
}

const TYPE_CONFIG = {
  doc: { icon: FileText, color: 'text-blue-500', bg: 'bg-blue-50', label: '飞书文档' },
  calendar: { icon: CalendarDays, color: 'text-orange-500', bg: 'bg-orange-50', label: '日历' },
  task: { icon: CheckSquare, color: 'text-green-500', bg: 'bg-green-50', label: '待办' },
  chat: { icon: MessageSquare, color: 'text-purple-500', bg: 'bg-purple-50', label: '群聊' },
};

export default function ContextSuggestions({ suggestions, loading, selectedId, onSelect, disabled }: Props) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center gap-2">
        <Sparkles className="h-3.5 w-3.5 text-primary shrink-0" />
        <span className="text-sm font-medium text-foreground">智能推荐</span>
        <span className="text-xs text-muted-foreground">基于你的飞书数据</span>
        {loading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground ml-auto" />}
      </div>

      {loading && suggestions.length === 0 ? (
        <div className="flex gap-3 overflow-x-auto pb-1">
          {Array.from({ length: 4 }).map((_, i) => (
            <div
              key={i}
              className="flex-none w-64 h-[110px] rounded-lg border border-border bg-card animate-pulse"
            />
          ))}
        </div>
      ) : !loading && suggestions.length === 0 ? (
        <div className="flex items-center gap-2 rounded-lg border border-dashed border-border bg-card/50 px-4 py-3">
          <span className="text-xs text-muted-foreground">请先在「设置」中配置飞书凭证，即可在此显示智能推荐</span>
        </div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-1 -mx-0.5 px-0.5">
          {suggestions.map((s) => {
            const cfg = TYPE_CONFIG[s.type];
            const Icon = cfg.icon;
            const isSelected = selectedId === s.id;
            return (
              <button
                key={s.id}
                type="button"
                disabled={disabled}
                onClick={() => !disabled && onSelect(s)}
                className={`flex-none w-64 rounded-lg border bg-card p-3.5 text-left transition-all shadow-sm
                  ${isSelected ? 'border-primary ring-1 ring-primary/30 bg-accent/50' : 'border-border hover:border-primary/40 hover:shadow-md'}
                  ${disabled ? 'opacity-50 pointer-events-none' : 'cursor-pointer'}`}
              >
                <div className="flex items-start gap-2.5 mb-2">
                  <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md ${cfg.bg}`}>
                    <Icon className={`h-3.5 w-3.5 ${cfg.color}`} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[11px] font-medium text-muted-foreground">{cfg.label}</div>
                    <div className="text-xs font-medium text-foreground truncate mt-0.5">{s.label}</div>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2 mb-2.5">{s.prompt}</p>
                <div className="flex items-center justify-between">
                  <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground">
                    {s.agents.length} 名成员
                  </span>
                  <span className={`text-[11px] font-medium ${isSelected ? 'text-primary' : 'text-muted-foreground'}`}>
                    {isSelected ? '✓ 已选用' : '点击使用 →'}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
