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
    advperm_state?: string;
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
    advperm_blueprints?: Array<Record<string, unknown>>;
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
  options?: { surfaces?: Array<'advperm' | 'form' | 'automation' | 'workflow' | 'dashboard' | 'role'>; force?: boolean },
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
    report_audience_open_id?: string;
    approval_owner?: string;
    approval_owner_open_id?: string;
    execution_owner?: string;
    execution_owner_open_id?: string;
    review_owner?: string;
    review_owner_open_id?: string;
    retrospective_owner?: string;
    retrospective_owner_open_id?: string;
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


// v8.6.20-r49：暴露 r34 / r37 / r43 / r44 给 Bitable 插件 UI 调用 — 让用户在
// 飞书插件里直接点按钮触发部署体检 / 取消任务 / 复跑任务 / 下载任务报告 Markdown，
// 不用再切到 Swagger 或 CLI。

export interface PreflightCheck {
  name: string;
  label: string;
  ok: boolean;
  detail: string;
  advisory: string;
  elapsed_ms: number;
}

export interface PreflightReport {
  ok: boolean;
  started_at: string;
  elapsed_ms: number;
  checks: PreflightCheck[];
}

export async function runPreflight(): Promise<PreflightReport> {
  const resp = await api.get<PreflightReport>('/api/v1/workflow/preflight');
  return resp.data;
}

export interface CancelTaskResponse {
  record_id: string;
  cancelled: boolean;
  already_pending: boolean;
  bitable_marked: boolean;
  queue_size: number;
}

export async function cancelTask(
  record_id: string,
  app_token?: string,
): Promise<CancelTaskResponse> {
  const params: Record<string, string> = {};
  if (app_token) params.app_token = app_token;
  const resp = await api.post<CancelTaskResponse>(
    `/api/v1/workflow/cancel/${encodeURIComponent(record_id)}`,
    null,
    { params },
  );
  return resp.data;
}

export interface ReplayTaskResponse {
  record_id: string;
  replayed: boolean;
  previous_status: string;
  fresh: boolean;
  cache_entries_cleared: number;
  next_step: string;
}

export async function replayTask(
  record_id: string,
  options: { app_token?: string; fresh?: boolean } = {},
): Promise<ReplayTaskResponse> {
  const params: Record<string, string> = {
    fresh: options.fresh ? 'true' : 'false',
  };
  if (options.app_token) params.app_token = options.app_token;
  const resp = await api.post<ReplayTaskResponse>(
    `/api/v1/workflow/replay/${encodeURIComponent(record_id)}`,
    null,
    { params },
  );
  return resp.data;
}

/**
 * 下载任务全量产出 Markdown — 走 download=1 触发浏览器另存为，避免在标签页里
 * 直接渲染长文档。返回 blob URL 供调用方做 anchor click。
 */
export async function downloadTaskMarkdown(
  record_id: string,
  app_token?: string,
): Promise<{ blobUrl: string; filename: string }> {
  const params: Record<string, string | boolean> = { download: true };
  if (app_token) params.app_token = app_token;
  const resp = await api.get<string>(
    `/api/v1/workflow/export/${encodeURIComponent(record_id)}`,
    { params, responseType: 'text' },
  );
  // FastAPI 返 Content-Disposition: attachment; filename="puff-c21-task-XXX.md"
  const dispo = (resp.headers as Record<string, string> | undefined)?.['content-disposition'] || '';
  const match = dispo.match(/filename="?([^";]+)"?/);
  const filename = match ? match[1] : `puff-c21-task-${record_id.slice(0, 8)}.md`;
  const blob = new Blob([resp.data], { type: 'text/markdown;charset=utf-8' });
  const blobUrl = URL.createObjectURL(blob);
  return { blobUrl, filename };
}

export interface ProgressEvent {
  task_id: string;
  event_type:
    | 'task.started'
    | 'wave.completed'
    | 'task.done'
    | 'task.error'
    | 'agent.started'
    | 'agent.completed'
    | 'agent.failed'
    | 'agent.token';
  payload: WorkflowProgressPayload;
  ts: string;
}

export interface WorkflowStepSnapshot {
  key: string;
  title: string;
  description: string;
  status: 'done' | 'running' | 'pending' | 'error';
  items?: string[];
  note?: string;
}

export interface AgentPipelineSnapshot {
  key: string;
  name: string;
  role: string;
  wave: 'Wave 1' | 'Wave 2' | 'Wave 3' | string;
  dependency: string;
  summary: string;
  status: 'done' | 'running' | 'pending' | 'error';
  duration_ms?: number | null;
  confidence?: number;
  fallback?: boolean;
  failed?: boolean;
  reason?: string;
  evidence_count?: number;
  action_count?: number;
}

export interface WorkflowProgressPayload extends Record<string, unknown> {
  stage?: string;
  progress?: number;
  reason?: string;
  chunk?: string;
  agent_id?: string;
  agent_name?: string;
  wave?: string;
  dependency?: string;
  duration_ms?: number | null;
  confidence?: number;
  fallback?: boolean;
  failed?: boolean;
  summary?: string;
  evidence_count?: number;
  action_count?: number;
  step_key?: string;
  step_title?: string;
  step_description?: string;
  step_status?: WorkflowStepSnapshot['status'];
  step_items?: string[];
  step_note?: string;
  workflow_steps?: WorkflowStepSnapshot[];
  agent_pipeline?: AgentPipelineSnapshot[];
}

export type WorkflowStreamStatus = 'connecting' | 'connected' | 'closed' | 'error';

function describeSseError(err: unknown): string {
  if (err instanceof Error) return err.message || err.name;
  if (typeof err === 'string') return err;
  return 'unknown error';
}

function requireStreamToken(data: { token?: unknown }): string {
  const token = typeof data.token === 'string' ? data.token.trim() : '';
  if (!token) {
    throw new Error('stream token missing');
  }
  return token;
}

export function subscribeTaskProgress(
  recordId: string,
  onEvent: (e: ProgressEvent) => void,
  onStatus?: (status: WorkflowStreamStatus, message?: string) => void,
): () => void {
  const normalizedRecordId = recordId.trim();
  if (!normalizedRecordId) {
    onStatus?.('error', 'record id missing');
    return () => undefined;
  }
  let es: EventSource | null = null;
  let closed = false;
  let terminal = false;
  const encodedRecordId = encodeURIComponent(normalizedRecordId);
  onStatus?.('connecting');

  const closeStream = (status: WorkflowStreamStatus, message?: string) => {
    if (terminal) return;
    terminal = true;
    onStatus?.(status, message);
    es?.close();
  };

  const handler = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as ProgressEvent;
      onEvent(data);
      if (data.event_type === 'task.done' || data.event_type === 'task.error') {
        closeStream(
          'closed',
          data.event_type === 'task.done' ? '工作流已完成' : '工作流异常结束',
        );
      }
    } catch (err) {
      console.error('[SSE] parse error:', err);
    }
  };

  void api
    .post<{ token: string }>(`/api/v1/workflow/stream-token/${encodedRecordId}`)
    .then((resp) => {
      if (closed) return;
      const token = requireStreamToken(resp.data);
      if (closed) return;
      es = new EventSource(
        `${BASE_URL}/api/v1/workflow/stream/${encodedRecordId}?token=${encodeURIComponent(token)}`,
      );
      es.onopen = () => {
        if (!closed && !terminal) onStatus?.('connected');
      };
      [
        'task.started',
        'wave.completed',
        'task.done',
        'task.error',
        'agent.started',
        'agent.completed',
        'agent.failed',
        'agent.token',
      ].forEach((evt) => es?.addEventListener(evt, handler as EventListener));
      es.onerror = () => {
        if (closed || terminal) return;
        closeStream('error', '实时流连接已断开，已回退到 Base 原生日志');
      };
    })
    .catch((err) => {
      if (!closed) {
        const message = describeSseError(err);
        onStatus?.('error', message);
        console.error(`[SSE] token error: ${message}`);
      }
    });

  return () => {
    closed = true;
    if (!terminal) {
      terminal = true;
      onStatus?.('closed');
    }
    es?.close();
  };
}
