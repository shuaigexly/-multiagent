import { describe, expect, it } from 'vitest';
import { isTerminalTaskStatus, resolveStreamEndState } from '../pages/workbenchStreamState';

describe('workbench stream end state', () => {
  it('keeps completed streams on the done screen', () => {
    expect(resolveStreamEndState('done', 'confirm')).toEqual({ step: 'done', error: null });
  });

  it('does not treat failed streams as completed work', () => {
    expect(resolveStreamEndState('failed', 'confirm')).toEqual({
      step: 'confirm',
      error: '任务执行失败，请重新确认',
    });
    expect(resolveStreamEndState('failed', 'input')).toEqual({
      step: 'input',
      error: '任务执行失败',
    });
  });

  it('routes cancelled and timeout endings away from the result screen', () => {
    expect(resolveStreamEndState('cancelled', 'confirm')).toEqual({
      step: 'input',
      error: '任务已取消',
    });
    expect(resolveStreamEndState('timeout', 'confirm')).toEqual({
      step: 'confirm',
      error: '实时连接超时，请刷新页面查看最新状态',
    });
  });

  it('identifies only task terminal states for connection recovery', () => {
    expect(isTerminalTaskStatus('done')).toBe(true);
    expect(isTerminalTaskStatus('failed')).toBe(true);
    expect(isTerminalTaskStatus('cancelled')).toBe(true);
    expect(isTerminalTaskStatus('running')).toBe(false);
    expect(isTerminalTaskStatus('timeout')).toBe(false);
  });
});
