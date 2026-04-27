import { useEffect, useRef } from 'react';
import type { SSEEvent } from '../services/types';
import { AGENT_PERSONAS } from './agentPersonas';

interface Props {
  events: SSEEvent[];
  status: 'running' | 'done' | 'failed' | 'idle';
}

type Persona = (typeof AGENT_PERSONAS)[keyof typeof AGENT_PERSONAS];
type AgentCardStatus = 'running' | 'completed' | 'waiting';

interface AgentCardData {
  agentKey: string;
  displayName: string;
  subtitle: string;
  avatar: string;
  color: string;
  lastEvent: SSEEvent;
  status: AgentCardStatus;
  isActive: boolean;
}

const PERSONA_ALIASES: Record<keyof typeof AGENT_PERSONAS, string[]> = {
  data_analyst: ['data_analyst', '数据分析师'],
  finance_advisor: ['finance_advisor', '财务顾问'],
  seo_advisor: ['seo_advisor', 'seo/增长顾问', 'seo增长顾问', '增长顾问'],
  content_manager: ['content_manager', '内容负责人'],
  product_manager: ['product_manager', '产品经理'],
  operations_manager: ['operations_manager', '运营负责人'],
  ceo_assistant: ['ceo_assistant', 'ceo 助理', 'ceo助理'],
};

function normalizeText(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, '');
}

function getTimestamp(event: SSEEvent, cache: Map<number, string>) {
  const rawTimestamp = event.payload?.timestamp;
  if (typeof rawTimestamp === 'string') {
    return new Date(rawTimestamp).toLocaleTimeString('zh-CN', { hour12: false });
  }

  const existing = cache.get(event.sequence);
  if (existing) return existing;

  const created = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  cache.set(event.sequence, created);
  return created;
}

function isCompletedEvent(event: SSEEvent) {
  return event.event_type.includes('completed') || event.event_type.includes('done');
}

function findPersona(agentName: string): Persona | undefined {
  const normalizedAgentName = normalizeText(agentName);

  return (Object.entries(AGENT_PERSONAS) as Array<[keyof typeof AGENT_PERSONAS, Persona]>).find(([key, persona]) => {
    const candidates = [
      key,
      persona.name,
      persona.title,
      ...PERSONA_ALIASES[key],
    ].map(normalizeText);

    return candidates.some(candidate =>
      candidate === normalizedAgentName ||
      candidate.includes(normalizedAgentName) ||
      normalizedAgentName.includes(candidate),
    );
  })?.[1];
}

function getHeaderStatus(status: Props['status']) {
  if (status === 'running') return { label: '执行中...', className: 'text-primary' };
  if (status === 'done') return { label: '已完成', className: 'text-success' };
  if (status === 'failed') return { label: '执行失败', className: 'text-destructive' };
  return { label: '等待中', className: 'text-muted-foreground' };
}

function getAgentStatus(lastEvent: SSEEvent, status: Props['status']): AgentCardStatus {
  if (isCompletedEvent(lastEvent)) return 'completed';
  if (status === 'running') return 'running';
  return 'waiting';
}

function getAgentStatusBadge(cardStatus: AgentCardStatus) {
  if (cardStatus === 'running') {
    return { label: '执行中', className: 'bg-warning/10 text-warning' };
  }
  if (cardStatus === 'completed') {
    return { label: '已完成', className: 'bg-success/10 text-success' };
  }
  return { label: '等待中', className: 'bg-muted text-muted-foreground' };
}

export default function ExecutionTimeline({ events, status }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const cacheRef = useRef(new Map<number, string>());

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events.length, status]);

  const systemEvents: SSEEvent[] = [];
  const agentGroups = new Map<string, SSEEvent[]>();

  for (const event of events) {
    const agentName = event.agent_name?.trim();
    if (!agentName) {
      systemEvents.push(event);
      continue;
    }

    const group = agentGroups.get(agentName);
    if (group) {
      group.push(event);
    } else {
      agentGroups.set(agentName, [event]);
    }
  }

  const latestAgentEvent = [...agentGroups.values()]
    .flat()
    .at(-1);

  const agentCards: AgentCardData[] = [...agentGroups.entries()].map(([agentKey, agentEvents]) => {
    const lastEvent = agentEvents[agentEvents.length - 1];
    const persona = findPersona(agentKey);

    return {
      agentKey,
      displayName: persona?.name ?? agentKey,
      subtitle: persona?.title ?? 'AI 团队成员',
      avatar: persona?.avatar ?? agentKey.slice(0, 1).toUpperCase(),
      color: persona?.color ?? '#636366',
      lastEvent,
      status: getAgentStatus(lastEvent, status),
      isActive: status === 'running' && latestAgentEvent?.sequence === lastEvent.sequence,
    };
  });

  const headerStatus = getHeaderStatus(status);

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border bg-secondary/50 px-3 py-2">
        <span className="text-xs font-medium text-foreground">执行日志</span>
        <span className={`text-xs ${headerStatus.className}`}>{headerStatus.label}</span>
      </div>

      <div ref={ref} className="max-h-96 overflow-y-auto p-3">
        {events.length === 0 ? (
          <div className="flex min-h-24 items-center justify-center text-sm text-muted-foreground">
            等待执行开始...
          </div>
        ) : (
          <div className="space-y-3">
            {agentCards.length > 0 && (
              <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-3">
                {agentCards.map((card) => {
                  const badge = getAgentStatusBadge(card.status);

                  return (
                    <div
                      key={card.agentKey}
                      className="rounded-xl border border-border bg-card/80 p-3 shadow-sm transition-colors"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <div
                            className={`relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-medium text-primary-foreground ${
                              card.isActive ? 'animate-pulse ring-2 ring-primary/40 ring-offset-2 ring-offset-background' : ''
                            }`}
                            style={{ backgroundColor: card.color }}
                          >
                            {card.avatar}
                          </div>
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium leading-tight text-foreground">
                              {card.displayName}
                            </div>
                            <div className="truncate text-[11px] text-muted-foreground">
                              {card.subtitle}
                            </div>
                          </div>
                        </div>

                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${badge.className}`}>
                          {badge.label}
                        </span>
                      </div>

                      <p className="mt-2 text-xs leading-relaxed text-muted-foreground line-clamp-2">
                        {card.lastEvent.message}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}

            {systemEvents.length > 0 && (
              <div className="space-y-2 border-t border-border/60 pt-2">
                {systemEvents.map((event) => (
                  <div key={event.sequence} className="flex items-start gap-2 text-xs text-muted-foreground">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/40" />
                    <span className="shrink-0 tabular-nums text-muted-foreground/80">
                      {getTimestamp(event, cacheRef.current)}
                    </span>
                    <span className="min-w-0 flex-1 leading-relaxed">{event.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
