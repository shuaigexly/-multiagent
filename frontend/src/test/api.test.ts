import { describe, expect, it, vi } from 'vitest';
import {
  cancelTask,
  confirmTask,
  createFeishuTask,
  deleteTask,
  getTaskResults,
  getTaskStatus,
  listTasks,
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
    await publishTask(taskId, ['doc'], { docTitle: '  ', chatId: '  ' });

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
      doc_title: null,
      chat_id: null,
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

  it('normalizes optional task api text payloads', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: [] });

    await confirmTask('task_1', ['data_analyst'], '  重点看留存  ');
    await publishTask('task_1', ['doc'], { docTitle: ' 周报 ', chatId: ' chat_1 ' });
    await listTasks({ limit: 20, offset: 0, status: ' done ', search: ' 增长 ' });
    await createFeishuTask(' 跟进转化异常 ', ' task_1 ');

    expect(postSpy).toHaveBeenCalledWith('/api/v1/tasks/task_1/confirm', {
      selected_modules: ['data_analyst'],
      user_instructions: '重点看留存',
    });
    expect(postSpy).toHaveBeenCalledWith('/api/v1/tasks/task_1/publish', {
      asset_types: ['doc'],
      doc_title: '周报',
      chat_id: 'chat_1',
    });
    expect(getSpy).toHaveBeenCalledWith('/api/v1/tasks', {
      params: { limit: 20, offset: 0, status: 'done', search: '增长' },
    });
    expect(postSpy).toHaveBeenCalledWith('/api/v1/feishu/tasks', {
      summary: '跟进转化异常',
      source_task_id: 'task_1',
    });

    getSpy.mockClear();
    await listTasks({ limit: 10, offset: 0, status: '  ', search: '  ' });
    expect(getSpy).toHaveBeenCalledWith('/api/v1/tasks', {
      params: { limit: 10, offset: 0 },
    });

    postSpy.mockRestore();
    getSpy.mockRestore();
  });

  it('rejects blank task ids before path based requests', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: {} });

    await expect(confirmTask('   ', ['data_analyst'])).rejects.toThrow('task id missing');
    expect(postSpy).not.toHaveBeenCalled();

    postSpy.mockRestore();
  });
});
