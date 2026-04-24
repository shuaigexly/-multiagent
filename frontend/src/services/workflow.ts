import { api, BASE_URL } from './http';

export interface WorkflowSetup {
  app_token: string;
  url: string;
  table_ids: {
    task: string;
    output: string;
    report: string;
    performance: string;
  };
}

export interface WorkflowStatus {
  running: boolean;
  state: Partial<WorkflowSetup>;
}

export interface TaskRecord {
  record_id: string;
  fields: Record<string, unknown>;
}

export async function setupWorkflow(name = '内容运营虚拟组织'): Promise<WorkflowSetup> {
  const resp = await api.post('/api/v1/workflow/setup', { name });
  return resp.data;
}

export async function startWorkflow(
  app_token: string,
  table_ids: WorkflowSetup['table_ids'],
  interval = 30,
): Promise<void> {
  await api.post('/api/v1/workflow/start', {
    app_token,
    table_ids,
    interval,
    analysis_every: 5,
  });
}

export async function stopWorkflow(): Promise<void> {
  await api.post('/api/v1/workflow/stop');
}

export async function getStatus(): Promise<WorkflowStatus> {
  const resp = await api.get('/api/v1/workflow/status');
  return resp.data;
}

export async function seedTask(
  app_token: string,
  table_id: string,
  title: string,
  dimension = '综合分析',
  background = '',
): Promise<{ record_id: string }> {
  const resp = await api.post('/api/v1/workflow/seed', {
    app_token,
    table_id,
    title,
    dimension,
    background,
  });
  return resp.data;
}

export async function listRecords(
  app_token: string,
  table_id: string,
  status?: string,
): Promise<{ count: number; records: TaskRecord[] }> {
  const resp = await api.get('/api/v1/workflow/records', {
    params: { app_token, table_id, ...(status ? { status } : {}) },
  });
  return resp.data;
}

export interface ProgressEvent {
  task_id: string;
  event_type: 'task.started' | 'wave.completed' | 'task.done' | 'task.error';
  payload: Record<string, unknown>;
  ts: string;
}

export function subscribeTaskProgress(
  recordId: string,
  onEvent: (e: ProgressEvent) => void,
): () => void {
  let es: EventSource | null = null;
  let closed = false;

  const handler = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as ProgressEvent;
      onEvent(data);
      if (data.event_type === 'task.done' || data.event_type === 'task.error') {
        es?.close();
      }
    } catch (err) {
      console.error('[SSE] parse error:', err);
    }
  };

  void api
    .post<{ token: string }>(`/api/v1/workflow/stream-token/${recordId}`)
    .then((resp) => {
      if (closed) return;
      es = new EventSource(
        `${BASE_URL}/api/v1/workflow/stream/${recordId}?token=${encodeURIComponent(resp.data.token)}`,
      );
      ['task.started', 'wave.completed', 'task.done', 'task.error'].forEach((evt) =>
        es?.addEventListener(evt, handler as EventListener),
      );
      es.onerror = () => {
        es?.close();
      };
    })
    .catch((err) => {
      console.error('[SSE] token error:', err);
    });

  return () => {
    closed = true;
    es?.close();
  };
}
