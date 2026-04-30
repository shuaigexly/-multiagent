import { describe, expect, it } from 'vitest';
import {
  appendWorkbenchStreamEvent,
  isTerminalTaskStatus,
  parseWorkbenchStreamEvent,
  resolveStreamEndState,
} from '../pages/workbenchStreamState';
import type { SSEEvent } from '../services/types';

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

  it('parses valid stream events and ignores malformed payloads', () => {
    expect(parseWorkbenchStreamEvent('not-json')).toBeNull();
    expect(parseWorkbenchStreamEvent(JSON.stringify({ sequence: 1 }))).toBeNull();
    expect(parseWorkbenchStreamEvent(JSON.stringify({ event_type: 'module.started' }))).toBeNull();
    expect(parseWorkbenchStreamEvent(JSON.stringify({
      sequence: 1,
      event_type: 'module.started',
      agent_name: '数据分析师',
      message: '开始分析',
      payload: null,
    }))).toEqual({
      sequence: 1,
      event_type: 'module.started',
      agent_name: '数据分析师',
      message: '开始分析',
      payload: {},
    });
    expect(parseWorkbenchStreamEvent(JSON.stringify({ event_type: 'stream.end', status: 'done' }))).toEqual({
      event_type: 'stream.end',
      status: 'done',
    });
  });

  it('deduplicates and caps workbench stream events', () => {
    const first: SSEEvent = {
      sequence: 1,
      event_type: 'module.started',
      agent_name: null,
      message: 'start',
      payload: {},
    };
    const second: SSEEvent = {
      sequence: 2,
      event_type: 'module.completed',
      agent_name: null,
      message: 'done',
      payload: {},
    };
    const timeout: SSEEvent = {
      sequence: 3,
      event_type: 'stream.timeout',
      agent_name: null,
      message: 'timeout',
      payload: {},
    };

    expect(appendWorkbenchStreamEvent([], first)).toEqual([first]);
    expect(appendWorkbenchStreamEvent([first], first)).toEqual([first]);
    expect(appendWorkbenchStreamEvent([first], timeout)).toEqual([first]);
    expect(appendWorkbenchStreamEvent([first], second, 1)).toEqual([second]);
  });
});
