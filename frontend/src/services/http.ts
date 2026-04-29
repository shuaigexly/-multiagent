import axios, { AxiosHeaders, type InternalAxiosRequestConfig } from 'axios';

export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const API_KEY_STORAGE_KEY = 'multiagent-lark.api-key';
const MAX_RUNTIME_API_KEY_LENGTH = 4096;

export function getRuntimeApiKey(): string {
  if (typeof window === 'undefined') return '';
  try {
    const value = (window.localStorage.getItem(API_KEY_STORAGE_KEY) || '').trim();
    return value.length <= MAX_RUNTIME_API_KEY_LENGTH ? value : '';
  } catch {
    return '';
  }
}

export function setRuntimeApiKey(value: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const normalized = value.trim();
    if (normalized.length > MAX_RUNTIME_API_KEY_LENGTH) return false;
    if (normalized) window.localStorage.setItem(API_KEY_STORAGE_KEY, normalized);
    else window.localStorage.removeItem(API_KEY_STORAGE_KEY);
    return true;
  } catch {
    return false;
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
