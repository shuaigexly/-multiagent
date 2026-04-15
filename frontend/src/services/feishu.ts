import axios from 'axios';

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const api = axios.create({ baseURL: BASE_URL });

export interface DriveFile {
  token: string;
  name: string;
  type: string;
  url: string | null;
  modified_time: string | null;
}

export interface CalendarEvent {
  event_id: string;
  summary: string;
  start_time: string | null;
  end_time: string | null;
  attendees_count: number;
  location: string;
  description: string | null;
}

export interface FeishuTask {
  guid: string;
  summary: string;
  due: string | null;
  status: string | null;
  completed: boolean;
  assignees: string[];
}

export interface FeishuChat {
  chat_id: string;
  name: string;
  description: string | null;
  chat_type: string;
}

export async function getDriveFiles(): Promise<DriveFile[]> {
  const r = await api.get('/api/v1/feishu/drive');
  return r.data.data;
}

export async function getCalendarEvents(): Promise<CalendarEvent[]> {
  const r = await api.get('/api/v1/feishu/calendar');
  return r.data.data;
}

export async function getFeishuTasks(): Promise<FeishuTask[]> {
  const r = await api.get('/api/v1/feishu/tasks');
  return r.data.data;
}

export async function getChats(): Promise<FeishuChat[]> {
  const r = await api.get('/api/v1/feishu/chats');
  return r.data.data;
}

export interface FeishuContext {
  drive: DriveFile[];
  calendar: CalendarEvent[];
  tasks: FeishuTask[];
}

export async function getFeishuContext(): Promise<FeishuContext> {
  const r = await api.get('/api/v1/feishu/context');
  return r.data;
}
