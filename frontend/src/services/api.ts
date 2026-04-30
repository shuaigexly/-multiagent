import type {
  TaskPlanResponse,
  TaskResultsResponse,
  TaskListItem,
  AgentInfo,
} from './types';
import { api, BASE_URL } from './http';

function taskPath(taskId: string): string {
  return encodeURIComponent(taskId);
}

export async function submitTask(
  inputText: string,
  file?: File,
  feishuContext?: object
): Promise<TaskPlanResponse> {
  const form = new FormData();
  const normalizedInputText = inputText.trim();
  if (normalizedInputText) form.append('input_text', normalizedInputText);
  if (file) form.append('file', file);
  if (feishuContext) form.append('feishu_context', JSON.stringify(feishuContext));
  const resp = await api.post('/api/v1/tasks', form);
  return resp.data;
}

export async function confirmTask(
  taskId: string,
  selectedModules: string[],
  userInstructions?: string | null
): Promise<{ task_id: string; status: string }> {
  const resp = await api.post(`/api/v1/tasks/${taskPath(taskId)}/confirm`, {
    selected_modules: selectedModules,
    user_instructions: userInstructions || null,
  });
  return resp.data;
}

export async function getTaskResults(taskId: string): Promise<TaskResultsResponse> {
  const resp = await api.get(`/api/v1/tasks/${taskPath(taskId)}/results`);
  return resp.data;
}

export async function getTaskStatus(taskId: string): Promise<{ status: string }> {
  const res = await api.get<{ status: string }>(`/api/v1/tasks/${taskPath(taskId)}/status`);
  return res.data;
}

export async function cancelTask(taskId: string): Promise<{ status: string }> {
  const res = await api.delete<{ status: string }>(`/api/v1/tasks/${taskPath(taskId)}`, {
    params: { action: 'cancel' },
  });
  return res.data;
}

export async function deleteTask(taskId: string): Promise<void> {
  await api.delete(`/api/v1/tasks/${taskPath(taskId)}`);
}

export async function listTasks(params?: {
  limit?: number;
  offset?: number;
  status?: string;
  search?: string;
}): Promise<TaskListItem[]> {
  const resp = await api.get('/api/v1/tasks', { params });
  return resp.data;
}

export async function publishTask(
  taskId: string,
  assetTypes: string[],
  options?: { docTitle?: string; chatId?: string }
): Promise<{ published: object[] }> {
  const resp = await api.post(`/api/v1/tasks/${taskPath(taskId)}/publish`, {
    asset_types: assetTypes,
    doc_title: options?.docTitle,
    chat_id: options?.chatId,
  });
  return resp.data;
}

export async function listAgents(): Promise<AgentInfo[]> {
  const resp = await api.get('/api/v1/tasks/agents');
  return resp.data.agents;
}

export async function getOAuthStatus(): Promise<{ authorized?: boolean }> {
  const resp = await api.get<{ authorized?: boolean }>('/api/v1/feishu/oauth/status');
  return resp.data;
}

export async function createFeishuTask(
  summary: string,
  sourceTaskId: string
): Promise<void> {
  await api.post('/api/v1/feishu/tasks', { summary, source_task_id: sourceTaskId });
}

export async function createSSEConnection(taskId: string): Promise<EventSource> {
  const encodedTaskId = taskPath(taskId);
  const resp = await api.post<{ token: string }>(`/api/v1/tasks/${encodedTaskId}/events-token`);
  const url = `${BASE_URL}/api/v1/tasks/${encodedTaskId}/events?token=${encodeURIComponent(resp.data.token)}`;
  return new EventSource(url);
}
