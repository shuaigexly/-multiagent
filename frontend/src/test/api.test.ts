import { describe, expect, it, vi } from 'vitest';
import {
  cancelTask,
  confirmTask,
  deleteTask,
  getTaskResults,
  getTaskStatus,
  publishTask,
  submitTask,
} from '../services/api';
import { api } from '../services/http';

describe('task api service', () => {
  it('encodes task ids in path based task endpoints', async () => {
    const taskId = 'task/a b?x=1';
    const encoded = 'task%2Fa%20b%3Fx%3D1';
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: {} });
    const deleteSpy = vi.spyOn(api, 'delete').mockResolvedValue({ data: {} });

    await confirmTask(taskId, ['ceo_assistant'], 'ship it');
    await getTaskResults(taskId);
    await getTaskStatus(taskId);
    await cancelTask(taskId);
    await deleteTask(taskId);
    await publishTask(taskId, ['doc']);

    expect(postSpy).toHaveBeenCalledWith(`/api/v1/tasks/${encoded}/confirm`, {
      selected_modules: ['ceo_assistant'],
      user_instructions: 'ship it',
    });
    expect(getSpy).toHaveBeenCalledWith(`/api/v1/tasks/${encoded}/results`);
    expect(getSpy).toHaveBeenCalledWith(`/api/v1/tasks/${encoded}/status`);
    expect(deleteSpy).toHaveBeenCalledWith(`/api/v1/tasks/${encoded}`, {
      params: { action: 'cancel' },
    });
    expect(deleteSpy).toHaveBeenCalledWith(`/api/v1/tasks/${encoded}`);
    expect(postSpy).toHaveBeenCalledWith(`/api/v1/tasks/${encoded}/publish`, {
      asset_types: ['doc'],
      doc_title: undefined,
      chat_id: undefined,
    });

    postSpy.mockRestore();
    getSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it('trims task input before submitting multipart payloads', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { task_id: 'task_1' } });

    await submitTask('  分析增长数据  ');

    const form = postSpy.mock.calls[0][1] as FormData;
    expect(postSpy).toHaveBeenCalledWith('/api/v1/tasks', expect.any(FormData));
    expect(form.get('input_text')).toBe('分析增长数据');

    postSpy.mockClear();
    await submitTask('   ');
    const blankForm = postSpy.mock.calls[0][1] as FormData;
    expect(blankForm.has('input_text')).toBe(false);

    postSpy.mockRestore();
  });
});
