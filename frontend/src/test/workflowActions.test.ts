/**
 * v8.6.20-r49: 前端 r34 / r43 / r44 端点客户端契约回归。
 *
 * 锁定：
 *  - cancelTask 走 POST /api/v1/workflow/cancel/{record_id} + 可选 ?app_token=
 *  - replayTask 走 POST /api/v1/workflow/replay/{record_id} + ?fresh=true|false
 *  - downloadTaskMarkdown 走 GET /api/v1/workflow/export/{record_id}?download=true，
 *    把 Content-Disposition 文件名提取出来
 *  - runPreflight 走 GET /api/v1/workflow/preflight
 */
import { describe, expect, it, vi, beforeAll } from 'vitest';
import {
  cancelTask,
  downloadTaskMarkdown,
  replayTask,
  runPreflight,
} from '../services/workflow';
import { api } from '../services/http';

beforeAll(() => {
  // jsdom 默认没有 URL.createObjectURL，downloadTaskMarkdown 用得着
  if (typeof URL.createObjectURL === 'undefined') {
    Object.defineProperty(URL, 'createObjectURL', {
      value: () => 'blob:mock',
      writable: true,
    });
  }
  if (typeof URL.revokeObjectURL === 'undefined') {
    Object.defineProperty(URL, 'revokeObjectURL', {
      value: () => undefined,
      writable: true,
    });
  }
});

describe('runPreflight', () => {
  it('GET /api/v1/workflow/preflight returns the report', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: { ok: true, started_at: '2026-05-01T00:00:00+00:00', elapsed_ms: 200, checks: [] },
    });

    const report = await runPreflight();
    expect(getSpy).toHaveBeenCalledWith('/api/v1/workflow/preflight');
    expect(report.ok).toBe(true);

    getSpy.mockRestore();
  });
});

describe('cancelTask', () => {
  it('POST /api/v1/workflow/cancel/{record_id} with app_token query', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        record_id: 'rec_x',
        cancelled: true,
        already_pending: false,
        bitable_marked: true,
        queue_size: 1,
      },
    });

    await cancelTask('rec_x', 'app_a');
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/workflow/cancel/rec_x',
      null,
      { params: { app_token: 'app_a' } },
    );

    postSpy.mockRestore();
  });

  it('POST without app_token uses empty params', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    await cancelTask('rec_y');
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/workflow/cancel/rec_y',
      null,
      { params: {} },
    );
    postSpy.mockRestore();
  });

  it('encodes record_id with special characters', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    await cancelTask('rec/x?y=1');
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/workflow/cancel/rec%2Fx%3Fy%3D1',
      null,
      { params: {} },
    );
    postSpy.mockRestore();
  });
});

describe('replayTask', () => {
  it('POST /api/v1/workflow/replay/{record_id} with fresh=false default', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        record_id: 'rec_re',
        replayed: true,
        previous_status: '已完成',
        fresh: false,
        cache_entries_cleared: 0,
        next_step: '...',
      },
    });

    await replayTask('rec_re');
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/workflow/replay/rec_re',
      null,
      { params: { fresh: 'false' } },
    );
    postSpy.mockRestore();
  });

  it('passes fresh=true and app_token when provided', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    await replayTask('rec_re', { app_token: 'app_b', fresh: true });
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/workflow/replay/rec_re',
      null,
      { params: { fresh: 'true', app_token: 'app_b' } },
    );
    postSpy.mockRestore();
  });
});

describe('downloadTaskMarkdown', () => {
  it('GET /api/v1/workflow/export/{record_id}?download=true and extracts filename', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: '# 测试\n\n内容',
      headers: {
        'content-disposition': 'attachment; filename="puff-c21-task-rec_xx.md"',
      },
    });

    const { filename, blobUrl } = await downloadTaskMarkdown('rec_xx', 'app_c');
    expect(getSpy).toHaveBeenCalledWith(
      '/api/v1/workflow/export/rec_xx',
      { params: { download: true, app_token: 'app_c' }, responseType: 'text' },
    );
    expect(filename).toBe('puff-c21-task-rec_xx.md');
    expect(blobUrl).toMatch(/^blob:/);

    getSpy.mockRestore();
  });

  it('falls back to derived filename when Content-Disposition missing', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: '...',
      headers: {},
    });
    const { filename } = await downloadTaskMarkdown('rec_no_dispo_long_id_here');
    expect(filename).toBe('puff-c21-task-rec_no_d.md');
    getSpy.mockRestore();
  });
});
