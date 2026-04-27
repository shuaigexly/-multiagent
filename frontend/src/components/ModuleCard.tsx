import { Check } from 'lucide-react';
import type { AgentInfo } from '../services/types';
import { AGENT_PERSONAS } from './agentPersonas';

interface Props {
  agent: AgentInfo;
  selected: boolean;
  onToggle: (id: string) => void;
  disabled?: boolean;
}

export default function ModuleCard({ agent, selected, onToggle, disabled = false }: Props) {
  const persona = AGENT_PERSONAS[agent.id] ?? {
    name: agent.name, title: 'AI 团队成员', avatar: agent.name.slice(0, 1),
    color: '#636366', personality: agent.suitable_for.slice(0, 3), tagline: agent.description,
  };

  return (
    <button
      type="button"
      className={`relative flex flex-col gap-2.5 rounded-lg border p-3.5 text-left transition-colors
        ${selected ? 'border-primary bg-accent shadow-sm' : 'border-border bg-card hover:border-primary/20 hover:bg-accent/30'}
        ${disabled ? 'opacity-50 pointer-events-none' : 'cursor-pointer'}`}
      onClick={() => !disabled && onToggle(agent.id)}
      aria-pressed={selected}
      disabled={disabled}
    >
      {/* Selection check */}
      {selected && (
        <div className="absolute top-2.5 right-2.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary">
          <Check className="h-3 w-3 text-primary-foreground" />
        </div>
      )}

      {/* Avatar + info */}
      <div className="flex items-center gap-2.5">
        <div
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-sm font-medium text-primary-foreground"
          style={{ backgroundColor: persona.color }}
        >
          {persona.avatar}
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-foreground leading-tight">{persona.name}</div>
          <div className="text-xs text-muted-foreground">{persona.title}</div>
        </div>
      </div>

      {/* Tagline */}
      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{persona.tagline}</p>

      {/* Tags */}
      <div className="flex flex-wrap gap-1">
        {persona.personality.map((tag) => (
          <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
            {tag}
          </span>
        ))}
      </div>
    </button>
  );
}
