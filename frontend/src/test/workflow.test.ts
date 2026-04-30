import { describe, expect, it, vi } from 'vitest';
import { createSSEConnection } from '../services/api';
import { api } from '../services/http';
import { subscribeTaskProgress } from '../services/workflow';

describe('workflow SSE subscription', () => {
  it('uses a short-lived stream token and closes cleanly', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'stream-token' } });
    const close = vi.fn();
    const addEventListener = vi.fn();
    const EventSourceMock = vi.fn().mockImplementation(() => ({ addEventListener, close }));
    vi.stubGlobal('EventSource', EventSourceMock);

    const statusSpy = vi.fn();
    const unsubscribe = subscribeTaskProgress('rec_123', vi.fn(), statusSpy);
    await vi.waitFor(() => expect(EventSourceMock).toHaveBeenCalledTimes(1));

    expect(statusSpy).toHaveBeenCalledWith('connecting');
    expect(postSpy).toHaveBeenCalledWith('/api/v1/workflow/stream-token/rec_123');
    expect(EventSourceMock.mock.calls[0][0]).toContain('/api/v1/workflow/stream/rec_123?token=stream-token');
    expect(addEventListener).toHaveBeenCalledWith('task.done', expect.any(Function));
    expect(addEventListener).toHaveBeenCalledWith('agent.started', expect.any(Function));
    expect(addEventListener).toHaveBeenCalledWith('agent.completed', expect.any(Function));
    expect(addEventListener).toHaveBeenCalledWith('agent.failed', expect.any(Function));

    unsubscribe();
    expect(statusSpy).toHaveBeenCalledWith('closed');
    expect(close).toHaveBeenCalled();
    postSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('encodes record ids before creating stream URLs', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'stream token/with symbols' } });
    const EventSourceMock = vi.fn().mockImplementation(() => ({ addEventListener: vi.fn(), close: vi.fn() }));
    vi.stubGlobal('EventSource', EventSourceMock);

    const unsubscribe = subscribeTaskProgress('rec/a b?x=1', vi.fn());
    await vi.waitFor(() => expect(EventSourceMock).toHaveBeenCalledTimes(1));

    expect(postSpy).toHaveBeenCalledWith('/api/v1/workflow/stream-token/rec%2Fa%20b%3Fx%3D1');
    expect(EventSourceMock.mock.calls[0][0]).toContain('/api/v1/workflow/stream/rec%2Fa%20b%3Fx%3D1?token=stream%20token%2Fwith%20symbols');

    unsubscribe();
    postSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('rejects blank workflow record ids without requesting stream tokens', () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'stream-token' } });
    const EventSourceMock = vi.fn();
    vi.stubGlobal('EventSource', EventSourceMock);

    const statusSpy = vi.fn();
    const unsubscribe = subscribeTaskProgress('   ', vi.fn(), statusSpy);
    unsubscribe();

    expect(statusSpy).toHaveBeenCalledWith('error', 'record id missing');
    expect(postSpy).not.toHaveBeenCalled();
    expect(EventSourceMock).not.toHaveBeenCalled();

    postSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('marks the stream closed when workflow reaches a terminal event', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'stream-token' } });
    const close = vi.fn();
    const listeners: Record<string, (event: MessageEvent) => void> = {};
    const addEventListener = vi.fn((eventName: string, handler: EventListener) => {
      listeners[eventName] = handler as (event: MessageEvent) => void;
    });
    const EventSourceMock = vi.fn().mockImplementation(() => ({ addEventListener, close }));
    vi.stubGlobal('EventSource', EventSourceMock);

    const eventSpy = vi.fn();
    const statusSpy = vi.fn();
    const unsubscribe = subscribeTaskProgress('rec_123', eventSpy, statusSpy);
    await vi.waitFor(() => expect(EventSourceMock).toHaveBeenCalledTimes(1));

    listeners['task.done']({
      data: JSON.stringify({ event_type: 'task.done', payload: {}, task_id: 'rec_123', ts: '2026-04-30T00:00:00Z' }),
    } as MessageEvent);

    expect(eventSpy).toHaveBeenCalledWith(expect.objectContaining({ event_type: 'task.done' }));
    expect(statusSpy).toHaveBeenCalledWith('closed', '工作流已完成');
    expect(close).toHaveBeenCalledTimes(1);

    unsubscribe();
    expect(statusSpy).toHaveBeenCalledTimes(2);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('does not report connected after a workflow stream was unsubscribed', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'stream-token' } });
    const source: { addEventListener: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn>; onopen?: () => void } = {
      addEventListener: vi.fn(),
      close: vi.fn(),
    };
    const EventSourceMock = vi.fn().mockImplementation(() => source);
    vi.stubGlobal('EventSource', EventSourceMock);

    const statusSpy = vi.fn();
    const unsubscribe = subscribeTaskProgress('rec_123', vi.fn(), statusSpy);
    await vi.waitFor(() => expect(EventSourceMock).toHaveBeenCalledTimes(1));

    unsubscribe();
    source.onopen?.();

    expect(statusSpy).toHaveBeenCalledWith('closed');
    expect(statusSpy).not.toHaveBeenCalledWith('connected');
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('rejects missing workflow stream tokens without opening EventSource', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const EventSourceMock = vi.fn();
    vi.stubGlobal('EventSource', EventSourceMock);

    const statusSpy = vi.fn();
    const unsubscribe = subscribeTaskProgress('rec_123', vi.fn(), statusSpy);
    await vi.waitFor(() => expect(errorSpy).toHaveBeenCalledTimes(1));

    expect(statusSpy).toHaveBeenCalledWith('error', 'stream token missing');
    expect(EventSourceMock).not.toHaveBeenCalled();
    unsubscribe();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('does not log raw token request errors that may contain API headers', async () => {
    const tokenError = Object.assign(new Error('token request failed'), {
      config: { headers: { 'X-API-Key': 'runtime-secret' } },
    });
    const postSpy = vi.spyOn(api, 'post').mockRejectedValue(tokenError);
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const statusSpy = vi.fn();
    const unsubscribe = subscribeTaskProgress('rec_123', vi.fn(), statusSpy);
    await vi.waitFor(() => expect(errorSpy).toHaveBeenCalledTimes(1));

    expect(statusSpy).toHaveBeenCalledWith('error', 'token request failed');
    expect(errorSpy.mock.calls[0]).toEqual(['[SSE] token error: token request failed']);
    expect(JSON.stringify(errorSpy.mock.calls)).not.toContain('runtime-secret');

    unsubscribe();
    postSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it('encodes task ids before creating task event streams', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'task token/with symbols' } });
    const EventSourceMock = vi.fn().mockImplementation(() => ({ close: vi.fn() }));
    vi.stubGlobal('EventSource', EventSourceMock);

    await createSSEConnection('task/a b?x=1');

    expect(postSpy).toHaveBeenCalledWith('/api/v1/tasks/task%2Fa%20b%3Fx%3D1/events-token');
    expect(EventSourceMock.mock.calls[0][0]).toContain('/api/v1/tasks/task%2Fa%20b%3Fx%3D1/events?token=task%20token%2Fwith%20symbols');

    postSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it('rejects missing task event stream tokens without opening EventSource', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const EventSourceMock = vi.fn();
    vi.stubGlobal('EventSource', EventSourceMock);

    await expect(createSSEConnection('task_1')).rejects.toThrow('stream token missing');
    expect(EventSourceMock).not.toHaveBeenCalled();

    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('rejects blank task event stream ids before requesting tokens', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { token: 'task-token' } });
    const EventSourceMock = vi.fn();
    vi.stubGlobal('EventSource', EventSourceMock);

    await expect(createSSEConnection('  ')).rejects.toThrow('task id missing');
    expect(postSpy).not.toHaveBeenCalled();
    expect(EventSourceMock).not.toHaveBeenCalled();

    postSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
