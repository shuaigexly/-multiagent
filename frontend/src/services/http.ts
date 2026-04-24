import axios from 'axios';

export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
export const API_KEY_STORAGE_KEY = 'multiagent-lark.api-key';

export function getRuntimeApiKey(): string {
  if (typeof window === 'undefined') return '';
  return window.localStorage.getItem(API_KEY_STORAGE_KEY) || '';
}

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const apiKey = getRuntimeApiKey();
  if (apiKey) {
    config.headers.set('X-API-Key', apiKey);
  }
  return config;
});
