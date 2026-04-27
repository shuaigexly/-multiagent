import { api, BASE_URL } from './http';

export interface WorkflowSetup {
  app_token: string;
  url: string;
  base_meta?: {
    base_type: string;
    mode: string;
    schema_version: string;
    initialized_at: string;
    source_template: string;
  };
  native_assets?: {
    status?: string;
    overall_state?: string;
    state_descriptions?: Record<string, string>;
    status_summary?: {
      overall_state?: string;
      total_assets?: number;
      counts?: Record<string, number>;
      groups?: Array<{
        key: string;
        label: string;
        count: number;
        state: string;
        counts: Record<string, number>;
      }>;
    };
    asset_groups?: Array<{
      key: string;
      label: string;
      count: number;
      state: string;
      counts: Record<string, number>;
    }>;
    form_blueprints?: Array<Record<string, unknown>>;
    automation_templates?: Array<Record<string, unknown>>;
    workflow_blueprints?: Array<Record<string, unknown>>;
    dashboard_blueprints?: Array<Record<string, unknown>>;
    role_blueprints?: Array<Record<string, unknown>>;
    manual_finish_checklist?: Array<Record<string, unknown>>;
    template_center_table_id?: string;
  };
  native_manifest?: {
    manifest_version?: string;
    install_order?: Array<Record<string, unknown>>;
    command_packs?: Array<Record<string, unknown>>;
    markdown?: string;
  };
  native_apply_report?: Array<Record<string, unknown>>;
  table_ids: {
    task: string;
    output: string;
    report: string;
    performance: string;
    datasource?: string;
    evidence?: string;
    review?: string;
    action?: string;
    review_history?: string;
    archive?: string;
    automation_log?: string;
    template?: string;
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

export interface RecordListResponse<T = TaskRecord> {
  count: number;
  records: T[];
}

export async function setupWorkflow(
  name = '内容运营虚拟组织',
  options?: {
    mode?: 'seed_demo' | 'prod_empty' | 'template_only';
    base_type?: 'template' | 'production' | 'validation';
    apply_native?: boolean;
  },
): Promise<WorkflowSetup> {
  const resp = await api.post('/api/v1/workflow/setup', {
    name,
    mode: options?.mode ?? 'seed_demo',
    base_type: options?.base_type ?? 'validation',
    apply_native: options?.apply_native ?? false,
  });
  return resp.data;
}

export async function applyNativeManifest(
  options?: { surfaces?: Array<'form' | 'automation' | 'workflow' | 'dashboard' | 'role'>; force?: boolean },
): Promise<{
  report: Array<Record<string, unknown>>;
  native_assets: WorkflowSetup['native_assets'];
  native_manifest: WorkflowSetup['native_manifest'];
}> {
  const resp = await api.post('/api/v1/workflow/native-manifest/apply', {
    surfaces: options?.surfaces ?? [],
    force: options?.force ?? false,
  });
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
  metadata?: {
    task_source?: string;
    business_owner?: string;
    audience_level?: string;
    target_audience?: string;
    output_purpose?: string;
    success_criteria?: string;
    constraints?: string;
    business_stage?: string;
    referenced_dataset?: string;
    template_name?: string;
    report_audience?: string;
    approval_owner?: string;
    execution_owner?: string;
    review_owner?: string;
    retrospective_owner?: string;
    review_sla_hours?: number;
  },
): Promise<{ record_id: string }> {
  const resp = await api.post('/api/v1/workflow/seed', {
    app_token,
    table_id,
    title,
    dimension,
    background,
    ...(metadata ?? {}),
  });
  return resp.data;
}

export async function listRecords(
  app_token: string,
  table_id: string,
  status?: string,
): Promise<RecordListResponse> {
  const resp = await api.get('/api/v1/workflow/records', {
    params: { app_token, table_id, ...(status ? { status } : {}) },
  });
  return resp.data;
}

export async function confirmTaskWorkflow(
  app_token: string,
  table_id: string,
  record_id: string,
  action: 'approve' | 'execute' | 'retrospective',
  actor = '',
): Promise<void> {
  await api.post('/api/v1/workflow/confirm', {
    app_token,
    table_id,
    record_id,
    action,
    actor,
  });
}

export interface ProgressEvent {
  task_id: string;
  event_type: 'task.started' | 'wave.completed' | 'task.done' | 'task.error' | 'agent.token';
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
      ['task.started', 'wave.completed', 'task.done', 'task.error', 'agent.token'].forEach((evt) =>
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
