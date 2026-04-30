import { describe, expect, it } from 'vitest';
import { formatRelativeTime } from '../pages/historyUtils';

describe('history page helpers', () => {
  it('formats relative task creation times', () => {
    const now = Date.parse('2026-04-30T12:00:00Z');

    expect(formatRelativeTime('2026-04-30T12:00:00Z', now)).toBe('刚刚');
    expect(formatRelativeTime('2026-04-30T11:58:00Z', now)).toContain('2');
  });

  it('does not throw on malformed task creation times', () => {
    expect(formatRelativeTime('not-a-date')).toBe('时间未知');
    expect(formatRelativeTime(null)).toBe('时间未知');
    expect(formatRelativeTime(undefined)).toBe('时间未知');
  });
});
