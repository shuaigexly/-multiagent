import type { SSEEvent } from '../services/types';

export type WorkbenchStep = 'input' | 'planning' | 'confirm' | 'running' | 'done';
export type StreamRecoverStep = 'input' | 'confirm';
export type WorkbenchStreamEndEvent = { event_type: 'stream.end'; status?: unknown };
export type WorkbenchStreamEvent = SSEEvent | WorkbenchStreamEndEvent;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseWorkbenchStreamEvent(raw: string): WorkbenchStreamEvent | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isRecord(parsed)) return null;
  const eventType = typeof parsed.event_type === 'string' ? parsed.event_type.trim() : '';
  if (!eventType) return null;

  if (eventType === 'stream.end') {
    return { event_type: 'stream.end', status: parsed.status };
  }

  const sequence = typeof parsed.sequence === 'number' && Number.isFinite(parsed.sequence)
    ? parsed.sequence
    : null;
  if (sequence === null) return null;

  return {
    sequence,
    event_type: eventType,
    agent_name: typeof parsed.agent_name === 'string' ? parsed.agent_name : null,
    message: typeof parsed.message === 'string' ? parsed.message : eventType,
    payload: isRecord(parsed.payload) ? parsed.payload : {},
  };
}

export function appendWorkbenchStreamEvent(
  events: SSEEvent[],
  event: SSEEvent,
  maxEvents = 200,
): SSEEvent[] {
  if (event.event_type === 'stream.timeout') return events;
  if (events.some((item) => item.sequence === event.sequence)) return events;

  const limit = Math.max(1, maxEvents);
  const next = [...events, event];
  return next.length <= limit ? next : next.slice(next.length - limit);
}

export function isTerminalTaskStatus(status: unknown): status is 'done' | 'failed' | 'cancelled' {
  return status === 'done' || status === 'failed' || status === 'cancelled';
}

export function resolveStreamEndState(
  status: unknown,
  recover: StreamRecoverStep,
): { step: WorkbenchStep; error: string | null } {
  if (status === 'done') {
    return { step: 'done', error: null };
  }
  if (status === 'failed') {
    return {
      step: recover,
      error: recover === 'confirm' ? '任务执行失败，请重新确认' : '任务执行失败',
    };
  }
  if (status === 'cancelled') {
    return { step: 'input', error: '任务已取消' };
  }
  if (status === 'timeout') {
    return {
      step: recover,
      error: '实时连接超时，请刷新页面查看最新状态',
    };
  }
  return {
    step: recover,
    error: '实时连接已结束，请刷新页面查看最新状态',
  };
}
