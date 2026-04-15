import axios from 'axios';
import type {
  TaskPlanResponse,
  TaskResultsResponse,
  TaskListItem,
  AgentInfo,
} from './types';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({ baseURL: BASE_URL });

export async function submitTask(
  inputText: string,
  file?: File,
  feishuContext?: object
): Promise<TaskPlanResponse> {
  const form = new FormData();
  if (inputText) form.append('input_text', inputText);
  if (file) form.append('file', file);
  if (feishuContext) form.append('feishu_context', JSON.stringify(feishuContext));
  const resp = await api.post('/api/v1/tasks', form);
  return resp.data;
}

export async function confirmTask(
  taskId: string,
  selectedModules: string[]
): Promise<{ task_id: string; status: string }> {
  const resp = await api.post(`/api/v1/tasks/${taskId}/confirm`, {
    selected_modules: selectedModules,
  });
  return resp.data;
}

export async function getTaskResults(taskId: string): Promise<TaskResultsResponse> {
  const resp = await api.get(`/api/v1/tasks/${taskId}/results`);
  return resp.data;
}

export async function listTasks(): Promise<TaskListItem[]> {
  const resp = await api.get('/api/v1/tasks');
  return resp.data;
}

export async function publishTask(
  taskId: string,
  assetTypes: string[],
  options?: { docTitle?: string; chatId?: string }
): Promise<{ published: object[] }> {
  const resp = await api.post(`/api/v1/tasks/${taskId}/publish`, {
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

export function createSSEConnection(taskId: string): EventSource {
  return new EventSource(`${BASE_URL}/api/v1/tasks/${taskId}/events`);
}
