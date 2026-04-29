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

    const unsubscribe = subscribeTaskProgress('rec_123', vi.fn());
    await vi.waitFor(() => expect(EventSourceMock).toHaveBeenCalledTimes(1));

    expect(postSpy).toHaveBeenCalledWith('/api/v1/workflow/stream-token/rec_123');
    expect(EventSourceMock.mock.calls[0][0]).toContain('/api/v1/workflow/stream/rec_123?token=stream-token');
    expect(addEventListener).toHaveBeenCalledWith('task.done', expect.any(Function));
    expect(addEventListener).toHaveBeenCalledWith('agent.started', expect.any(Function));
    expect(addEventListener).toHaveBeenCalledWith('agent.completed', expect.any(Function));
    expect(addEventListener).toHaveBeenCalledWith('agent.failed', expect.any(Function));

    unsubscribe();
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

  it('does not log raw token request errors that may contain API headers', async () => {
    const tokenError = Object.assign(new Error('token request failed'), {
      config: { headers: { 'X-API-Key': 'runtime-secret' } },
    });
    const postSpy = vi.spyOn(api, 'post').mockRejectedValue(tokenError);
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);

    const unsubscribe = subscribeTaskProgress('rec_123', vi.fn());
    await vi.waitFor(() => expect(errorSpy).toHaveBeenCalledTimes(1));

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
});
