// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ExecutionTimeline from '../components/ExecutionTimeline';
import type { SSEEvent } from '../services/types';

describe('ExecutionTimeline', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('falls back to a stable local time for invalid event timestamps', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 2, 9, 8, 7));

    const events: SSEEvent[] = [{
      sequence: 1,
      event_type: 'system',
      agent_name: null,
      message: 'workflow started',
      payload: { timestamp: 'not-a-date' },
    }];

    render(<ExecutionTimeline events={events} status="running" />);

    expect(screen.queryByText('Invalid Date')).toBeNull();
    expect(screen.getByText('09:08:07')).toBeTruthy();
  });
});
