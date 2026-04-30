import { describe, expect, it } from 'vitest';
import { formatCalendarRange, formatDateTime, formatDisplayTime } from '../pages/feishuWorkspaceUtils';

describe('feishu workspace time helpers', () => {
  it('rejects invalid or empty second timestamps', () => {
    expect(formatDateTime(null)).toBeNull();
    expect(formatDateTime('')).toBeNull();
    expect(formatDateTime('0')).toBeNull();
    expect(formatDateTime('Infinity')).toBeNull();
    expect(formatDisplayTime('not-a-number')).toBeNull();
  });

  it('formats valid calendar ranges and falls back for malformed ranges', () => {
    expect(formatCalendarRange(null, '1710003600')).toBe('时间未知');
    expect(formatCalendarRange('1710000000', '1710003600')).not.toBe('时间未知');
    expect(formatDisplayTime('1710000000')).toEqual(expect.any(String));
  });
});
