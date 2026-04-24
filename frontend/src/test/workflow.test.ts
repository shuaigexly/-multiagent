import { describe, expect, it, vi } from 'vitest';
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

    unsubscribe();
    expect(close).toHaveBeenCalled();
    postSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
