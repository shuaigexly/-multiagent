import { api } from './http';

export const LLM_CONFIGURED_STORAGE_KEY = 'multiagent-lark.llm-configured';

export interface ConfigStatus {
  set: boolean;
  value: string | null;
}

export type ConfigMap = Record<string, ConfigStatus>;

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
}

export interface ConfigSaveItem {
  key: string;
  value: string | null;
}

export async function getConfig(): Promise<ConfigMap> {
  const response = await api.get('/api/v1/config');
  return response.data;
}

export async function saveConfig(key: string, value: string): Promise<void> {
  await api.post('/api/v1/config', { key, value });
}

export async function saveConfigs(configs: ConfigSaveItem[]): Promise<void> {
  await api.post('/api/v1/config', { configs });
}

export async function testLLM(
  apiKey: string,
  baseUrl: string,
  model: string
): Promise<ConnectionTestResult> {
  const response = await api.post('/api/v1/config/test-llm', {
    api_key: apiKey,
    base_url: baseUrl,
    model,
  });
  return response.data;
}

export async function testFeishu(
  appId: string,
  appSecret: string,
  region: string
): Promise<ConnectionTestResult> {
  const response = await api.post('/api/v1/config/test-feishu', {
    app_id: appId,
    app_secret: appSecret,
    region,
  });
  return response.data;
}

export function setStoredLLMConfigured(configured: boolean): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(LLM_CONFIGURED_STORAGE_KEY, configured ? 'true' : 'false');
}

export function isStoredLLMConfigured(): boolean {
  if (typeof window === 'undefined') return false;
  return window.localStorage.getItem(LLM_CONFIGURED_STORAGE_KEY) === 'true';
}
