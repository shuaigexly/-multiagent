import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';

export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const API_KEY_STORAGE_KEY = 'multiagent-lark.api-key';

export function getRuntimeApiKey(): string {
  if (typeof window === 'undefined') return '';
  try {
    return window.localStorage.getItem(API_KEY_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

export function attachRuntimeApiKeyHeader(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  const apiKey = getRuntimeApiKey();
  if (apiKey) {
    config.headers = AxiosHeaders.from(config.headers);
    config.headers.set('X-API-Key', apiKey);
  }
  return config;
}

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
});

api.interceptors.request.use(attachRuntimeApiKeyHeader);
