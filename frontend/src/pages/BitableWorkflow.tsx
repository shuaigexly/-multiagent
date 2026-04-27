import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  ArrowUpRight,
  Briefcase,
  CheckCircle2,
  Clock3,
  Database,
  FileCheck2,
  FileSearch,
  Flame,
  Layers3,
  Loader2,
  Pause,
  Play,
  PlusCircle,
  RefreshCw,
  ShieldAlert,
  Sparkles,
  Target,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Progress } from '@/components/ui/progress';
import { toast } from '@/hooks/use-toast';
import {
  applyNativeManifest,
  confirmTaskWorkflow,
  getStatus,
  listRecords,
  seedTask,
  setupWorkflow,
  startWorkflow,
  stopWorkflow,
  subscribeTaskProgress,
  type ProgressEvent,
  type RecordListResponse,
  type TaskRecord,
  type WorkflowSetup,
} from '@/services/workflow';

interface LiveEvent {
  taskId: string;
  stage: string;
  progress: number;
  status: 'running' | 'done' | 'error';
  updatedAt: string;
}

const STATUS_STYLE: Record<string, { chip: string; lane: string; label: string; surface: string }> = {
  待分析: {
    chip: 'border border-slate-200 bg-slate-100 text-slate-700',
    lane: 'from-slate-50 via-white to-slate-50',
    label: '等待进入波次',
    surface: 'from-slate-100 via-white to-slate-50',
  },
  分析中: {
    chip: 'border border-amber-200 bg-amber-100 text-amber-800',
    lane: 'from-amber-50 via-white to-yellow-50',
    label: '多岗协作执行中',
    surface: 'from-amber-100 via-white to-yellow-50',
  },
  已完成: {
    chip: 'border border-emerald-200 bg-emerald-100 text-emerald-800',
    lane: 'from-emerald-50 via-white to-cyan-50',
    label: '已形成决策产物',
    surface: 'from-emerald-100 via-white to-cyan-50',
  },
  已归档: {
    chip: 'border border-sky-200 bg-sky-100 text-sky-800',
    lane: 'from-sky-50 via-white to-indigo-50',
    label: '已沉淀至历史资产',
    surface: 'from-sky-100 via-white to-indigo-50',
  },
};

const PURPOSE_STYLE: Record<string, string> = {
  经营诊断: 'border-sky-200 bg-sky-50 text-sky-700',
  管理决策: 'border-rose-200 bg-rose-50 text-rose-700',
  执行跟进: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  汇报展示: 'border-violet-200 bg-violet-50 text-violet-700',
  补数核验: 'border-amber-200 bg-amber-50 text-amber-700',
};

const RECOMMENDATION_STYLE: Record<string, string> = {
  直接采用: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  补数后复核: 'border-amber-200 bg-amber-50 text-amber-700',
  建议重跑: 'border-rose-200 bg-rose-50 text-rose-700',
};

const CONFIDENCE_STYLE: Record<string, string> = {
  high: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  medium: 'border-amber-200 bg-amber-50 text-amber-700',
  low: 'border-rose-200 bg-rose-50 text-rose-700',
};

const EVIDENCE_GRADE_STYLE: Record<string, string> = {
  硬证据: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  推断: 'border-sky-200 bg-sky-50 text-sky-700',
  待验证: 'border-amber-200 bg-amber-50 text-amber-700',
};

const ROUTE_STYLE: Record<string, string> = {
  直接汇报: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  等待拍板: 'border-rose-200 bg-rose-50 text-rose-700',
  直接执行: 'border-sky-200 bg-sky-50 text-sky-700',
  补数复核: 'border-amber-200 bg-amber-50 text-amber-700',
  重新分析: 'border-orange-200 bg-orange-50 text-orange-700',
};

const RESPONSIBILITY_STYLE: Record<string, string> = {
  系统调度: 'border-slate-200 bg-slate-100 text-slate-700',
  汇报对象: 'border-cyan-200 bg-cyan-50 text-cyan-700',
  拍板人: 'border-rose-200 bg-rose-50 text-rose-700',
  执行人: 'border-sky-200 bg-sky-50 text-sky-700',
  复核人: 'border-amber-200 bg-amber-50 text-amber-700',
  复盘负责人: 'border-violet-200 bg-violet-50 text-violet-700',
  已归档: 'border-emerald-200 bg-emerald-50 text-emerald-700',
};

const NATIVE_ACTION_STYLE: Record<string, string> = {
  等待分析完成: 'border-slate-200 bg-slate-100 text-slate-700',
  发送汇报: 'border-cyan-200 bg-cyan-50 text-cyan-700',
  管理拍板: 'border-rose-200 bg-rose-50 text-rose-700',
  执行落地: 'border-sky-200 bg-sky-50 text-sky-700',
  安排复核: 'border-amber-200 bg-amber-50 text-amber-700',
  进入复盘: 'border-violet-200 bg-violet-50 text-violet-700',
  归档沉淀: 'border-emerald-200 bg-emerald-50 text-emerald-700',
};

const EXCEPTION_STATUS_STYLE: Record<string, string> = {
  正常: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  需关注: 'border-amber-200 bg-amber-50 text-amber-700',
  已异常: 'border-rose-200 bg-rose-50 text-rose-700',
};

const ACTION_STATUS_STYLE: Record<string, string> = {
  已完成: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  已跳过: 'border-slate-200 bg-slate-100 text-slate-600',
  执行失败: 'border-rose-200 bg-rose-50 text-rose-700',
  待执行: 'border-amber-200 bg-amber-50 text-amber-700',
};

const ACTION_TYPE_STYLE: Record<string, string> = {
  发送汇报: 'border-cyan-200 bg-cyan-50 text-cyan-700',
  创建执行任务: 'border-sky-200 bg-sky-50 text-sky-700',
  创建复核任务: 'border-amber-200 bg-amber-50 text-amber-700',
  自动跟进任务: 'border-violet-200 bg-violet-50 text-violet-700',
  工作流记录: 'border-slate-200 bg-slate-100 text-slate-700',
};

const ARCHIVE_STATUS_STYLE: Record<string, string> = {
  待汇报: 'border-cyan-200 bg-cyan-50 text-cyan-700',
  待拍板: 'border-rose-200 bg-rose-50 text-rose-700',
  待执行: 'border-sky-200 bg-sky-50 text-sky-700',
  待复核: 'border-amber-200 bg-amber-50 text-amber-700',
  已归档: 'border-slate-200 bg-slate-100 text-slate-700',
};

const EVIDENCE_USAGE_STYLE: Record<string, string> = {
  insight: 'border-sky-200 bg-sky-50 text-sky-700',
  opportunity: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  risk: 'border-rose-200 bg-rose-50 text-rose-700',
  decision: 'border-violet-200 bg-violet-50 text-violet-700',
};

const PURPOSE_OPTIONS = ['经营诊断', '管理决策', '执行跟进', '汇报展示', '补数核验'] as const;
const SETUP_MODE_OPTIONS = ['seed_demo', 'prod_empty', 'template_only'] as const;
const BASE_TYPE_OPTIONS = ['validation', 'production', 'template'] as const;
const TASK_SOURCE_OPTIONS = ['手工创建', '表单提交', '跟进任务', '复核任务', '外部系统同步'] as const;
const BUSINESS_OWNER_OPTIONS = ['综合经营', '增长', '产品', '内容', '运营', '财务'] as const;
const AUDIENCE_LEVEL_OPTIONS = ['负责人', '部门管理层', 'CEO / CXO'] as const;
const STATUS_ORDER = ['待分析', '分析中', '已完成', '已归档'] as const;
const ASSET_STATE_STYLE: Record<string, string> = {
  created: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  api_supported: 'border-sky-200 bg-sky-50 text-sky-700',
  blueprint_ready: 'border-violet-200 bg-violet-50 text-violet-700',
  manual_finish_required: 'border-amber-200 bg-amber-50 text-amber-800',
  permission_blocked: 'border-rose-200 bg-rose-50 text-rose-700',
};
const ASSET_STATE_LABEL: Record<string, string> = {
  created: '已创建',
  api_supported: 'API 可接',
  blueprint_ready: '蓝图就绪',
  manual_finish_required: '待人工补完',
  permission_blocked: '权限受阻',
};
const APPLY_REPORT_STYLE: Record<string, string> = {
  created: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  skipped: 'border-slate-200 bg-slate-100 text-slate-600',
  manual_finish_required: 'border-amber-200 bg-amber-50 text-amber-800',
  permission_blocked: 'border-rose-200 bg-rose-50 text-rose-700',
};

function textValue(value: unknown) {
  return typeof value === 'string' ? value : '';
}

function numberValue(value: unknown) {
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function booleanValue(value: unknown) {
  if (typeof value === 'boolean') return value;
  if (typeof value === 'number') return value > 0;
  if (typeof value === 'string') return ['true', '1', 'yes'].includes(value.toLowerCase());
  return false;
}

function safeProgress(value: unknown) {
  const raw = numberValue(value);
  const normalized = raw <= 1 ? raw * 100 : raw;
  return Math.max(0, Math.min(100, normalized));
}

function clampScore(value: unknown) {
  return Math.max(0, Math.min(5, Math.round(numberValue(value))));
}

function parseTimeValue(value: unknown) {
  if (typeof value === 'number') {
    return value > 10_000_000_000 ? value : value * 1000;
  }
  if (typeof value === 'string') {
    const ts = Date.parse(value);
    return Number.isFinite(ts) ? ts : 0;
  }
  return 0;
}

function formatRelativeTime(value: string) {
  if (!value) return '刚刚更新';
  const diff = Date.now() - new Date(value).getTime();
  const minutes = Math.max(0, Math.round(diff / 60000));
  if (minutes < 1) return '刚刚更新';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.round(hours / 24)} 天前`;
}

function formatDateValue(value: unknown) {
  const ts = parseTimeValue(value);
  if (!ts) return '未安排';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(ts));
}

function hoursSince(value: unknown) {
  const ts = parseTimeValue(value);
  if (!ts) return 0;
  return Math.max(0, Math.round((Date.now() - ts) / 3_600_000));
}

function splitListText(value: unknown, limit = 4) {
  return textValue(value)
    .split(/\n+/)
    .map((line) => line.replace(/^[-•\s]+/, '').trim())
    .filter(Boolean)
    .slice(0, limit);
}

function taskField(task: TaskRecord | null | undefined, fieldName: string) {
  return task?.fields?.[fieldName];
}

function taskTitle(task: TaskRecord | null | undefined, fieldName = '任务标题') {
  return textValue(taskField(task, fieldName));
}

function recordTimestamp(record: TaskRecord, fields: string[]) {
  for (const field of fields) {
    const ts = parseTimeValue(record.fields?.[field]);
    if (ts > 0) return ts;
  }
  return 0;
}

function buildLatestRecordMap(records: TaskRecord[], titleField: string, timeFields: string[]) {
  const grouped = new Map<string, TaskRecord>();
  records.forEach((record) => {
    const key = taskTitle(record, titleField);
    if (!key) return;
    const prev = grouped.get(key);
    if (!prev || recordTimestamp(record, timeFields) >= recordTimestamp(prev, timeFields)) {
      grouped.set(key, record);
    }
  });
  return grouped;
}

function buildGroupedRecordMap(records: TaskRecord[], titleField: string, timeFields: string[]) {
  const grouped = new Map<string, TaskRecord[]>();
  records.forEach((record) => {
    const key = taskTitle(record, titleField);
    if (!key) return;
    grouped.set(key, [...(grouped.get(key) || []), record]);
  });
  grouped.forEach((items, key) => {
    grouped.set(
      key,
      [...items].sort((left, right) => recordTimestamp(right, timeFields) - recordTimestamp(left, timeFields)),
    );
  });
  return grouped;
}

function laneTasks(tasks: TaskRecord[], status: string) {
  return tasks.filter((task) => textValue(task.fields?.状态) === status);
}

function taskDependsOn(task: TaskRecord, taskNumber: string) {
  if (!taskNumber) return false;
  const deps = textValue(task.fields?.依赖任务编号)
    .split(/[,，;；\n\s]+/)
    .map((item) => item.replace(/^T/i, '').replace(/^0+/, '').trim())
    .filter(Boolean);
  const normalized = taskNumber.replace(/^T/i, '').replace(/^0+/, '').trim();
  return deps.includes(normalized);
}

function taskReviewAction(task: TaskRecord | null | undefined, latestReview: TaskRecord | null | undefined) {
  return textValue(taskField(task, '最新评审动作')) || textValue(latestReview?.fields?.推荐动作);
}

function taskReadinessScore(task: TaskRecord | null | undefined, latestReview: TaskRecord | null | undefined) {
  const taskScore = clampScore(taskField(task, '汇报就绪度'));
  if (taskScore > 0) return taskScore;
  if (!latestReview) return 0;
  const values = ['真实性', '决策性', '可执行性', '闭环准备度'].map((field) => clampScore(latestReview.fields?.[field]));
  const scored = values.filter((value) => value > 0);
  if (!scored.length) return 0;
  return Math.round(scored.reduce((sum, value) => sum + value, 0) / scored.length);
}

function taskWorkflowRoute(task: TaskRecord | null | undefined) {
  return textValue(taskField(task, '工作流路由'));
}

function taskResponsibilityRole(task: TaskRecord | null | undefined) {
  return textValue(taskField(task, '当前责任角色'));
}

function taskNativeAction(task: TaskRecord | null | undefined) {
  return textValue(taskField(task, '当前原生动作'));
}

function taskExceptionStatus(task: TaskRecord | null | undefined) {
  return textValue(taskField(task, '异常状态'));
}

function taskExceptionType(task: TaskRecord | null | undefined) {
  return textValue(taskField(task, '异常类型'));
}

function yesNoLabel(value: unknown) {
  return booleanValue(value) ? '是' : '否';
}

function sortTasksByLatest(tasks: TaskRecord[]) {
  return [...tasks].sort(
    (left, right) => recordTimestamp(right, ['最近更新', '创建时间']) - recordTimestamp(left, ['最近更新', '创建时间']),
  );
}

function scoreStars(score: unknown) {
  const clamped = clampScore(score);
  return `${'★'.repeat(clamped)}${'☆'.repeat(Math.max(0, 5 - clamped))}`;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">
      {text}
    </div>
  );
}

function objectList(value: unknown) {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

export default function BitableWorkflow() {
  const [setup, setSetupState] = useState<WorkflowSetup | null>(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [setupName, setSetupName] = useState('内容运营虚拟组织');
  const [setupMode, setSetupMode] = useState<(typeof SETUP_MODE_OPTIONS)[number]>('seed_demo');
  const [setupBaseType, setSetupBaseType] = useState<(typeof BASE_TYPE_OPTIONS)[number]>('validation');
  const [setupApplyNative, setSetupApplyNative] = useState(true);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [reportRecords, setReportRecords] = useState<TaskRecord[]>([]);
  const [evidenceRecords, setEvidenceRecords] = useState<TaskRecord[]>([]);
  const [reviewRecords, setReviewRecords] = useState<TaskRecord[]>([]);
  const [actionRecords, setActionRecords] = useState<TaskRecord[]>([]);
  const [reviewHistoryRecords, setReviewHistoryRecords] = useState<TaskRecord[]>([]);
  const [archiveRecords, setArchiveRecords] = useState<TaskRecord[]>([]);
  const [automationLogRecords, setAutomationLogRecords] = useState<TaskRecord[]>([]);
  const [templateRecords, setTemplateRecords] = useState<TaskRecord[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [liveEvents, setLiveEvents] = useState<Record<string, LiveEvent>>({});
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskBackground, setNewTaskBackground] = useState('');
  const [newTaskAudience, setNewTaskAudience] = useState('');
  const [newTaskPurpose, setNewTaskPurpose] = useState<(typeof PURPOSE_OPTIONS)[number]>('经营诊断');
  const [newTaskSource, setNewTaskSource] = useState<(typeof TASK_SOURCE_OPTIONS)[number]>('手工创建');
  const [newTaskBusinessOwner, setNewTaskBusinessOwner] = useState<(typeof BUSINESS_OWNER_OPTIONS)[number]>('综合经营');
  const [newTaskAudienceLevel, setNewTaskAudienceLevel] = useState<(typeof AUDIENCE_LEVEL_OPTIONS)[number]>('负责人');
  const [newTaskSuccessCriteria, setNewTaskSuccessCriteria] = useState('');
  const [newTaskConstraints, setNewTaskConstraints] = useState('');
  const [newTaskDatasetRef, setNewTaskDatasetRef] = useState('');
  const [newTaskReportAudience, setNewTaskReportAudience] = useState('');
  const [newTaskApprovalOwner, setNewTaskApprovalOwner] = useState('');
  const [newTaskExecutionOwner, setNewTaskExecutionOwner] = useState('');
  const [newTaskReviewOwner, setNewTaskReviewOwner] = useState('');
  const [newTaskRetrospectiveOwner, setNewTaskRetrospectiveOwner] = useState('');
  const [newTaskReviewSla, setNewTaskReviewSla] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const progressSubscriptionsRef = useRef<Map<string, () => void>>(new Map());

  useEffect(() => {
    (async () => {
      try {
        const st = await getStatus();
        setRunning(st.running);
        if (st.state?.app_token && st.state?.table_ids) {
          setSetupState({
            app_token: st.state.app_token,
            url: st.state.url || '',
            base_meta: st.state.base_meta,
            native_assets: st.state.native_assets,
            native_manifest: st.state.native_manifest,
            native_apply_report: st.state.native_apply_report,
            table_ids: st.state.table_ids as WorkflowSetup['table_ids'],
          });
          if (textValue(st.state.base_meta?.mode) && SETUP_MODE_OPTIONS.includes(st.state.base_meta.mode as (typeof SETUP_MODE_OPTIONS)[number])) {
            setSetupMode(st.state.base_meta.mode as (typeof SETUP_MODE_OPTIONS)[number]);
          }
          if (textValue(st.state.base_meta?.base_type) && BASE_TYPE_OPTIONS.includes(st.state.base_meta.base_type as (typeof BASE_TYPE_OPTIONS)[number])) {
            setSetupBaseType(st.state.base_meta.base_type as (typeof BASE_TYPE_OPTIONS)[number]);
          }
        }
      } catch (err) {
        console.warn('getStatus failed', err);
      }
    })();
  }, []);

  const refreshTasks = useCallback(async () => {
    if (!setup) return;
    try {
      const emptyRecords: RecordListResponse = { count: 0, records: [] };
      const taskPromise = listRecords(setup.app_token, setup.table_ids.task);
      const evidencePromise = setup.table_ids.evidence
        ? listRecords(setup.app_token, setup.table_ids.evidence).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const reviewPromise = setup.table_ids.review
        ? listRecords(setup.app_token, setup.table_ids.review).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const reportPromise = setup.table_ids.report
        ? listRecords(setup.app_token, setup.table_ids.report).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const actionPromise = setup.table_ids.action
        ? listRecords(setup.app_token, setup.table_ids.action).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const reviewHistoryPromise = setup.table_ids.review_history
        ? listRecords(setup.app_token, setup.table_ids.review_history).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const archivePromise = setup.table_ids.archive
        ? listRecords(setup.app_token, setup.table_ids.archive).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const automationLogPromise = setup.table_ids.automation_log
        ? listRecords(setup.app_token, setup.table_ids.automation_log).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);
      const templatePromise = setup.table_ids.template
        ? listRecords(setup.app_token, setup.table_ids.template).catch(() => emptyRecords)
        : Promise.resolve(emptyRecords);

      const [taskResp, evidenceResp, reviewResp, reportResp, actionResp, reviewHistoryResp, archiveResp, automationLogResp, templateResp] = await Promise.all([
        taskPromise,
        evidencePromise,
        reviewPromise,
        reportPromise,
        actionPromise,
        reviewHistoryPromise,
        archivePromise,
        automationLogPromise,
        templatePromise,
      ]);

      setTasks(taskResp.records);
      setEvidenceRecords(evidenceResp.records);
      setReviewRecords(reviewResp.records);
      setReportRecords(reportResp.records);
      setActionRecords(actionResp.records);
      setReviewHistoryRecords(reviewHistoryResp.records);
      setArchiveRecords(archiveResp.records);
      setAutomationLogRecords(automationLogResp.records);
      setTemplateRecords(templateResp.records);
    } catch (err) {
      toast({ title: '拉取任务失败', description: String(err), variant: 'destructive' });
    }
  }, [setup]);

  useEffect(() => {
    if (!setup) return;
    refreshTasks();
    const iv = setInterval(refreshTasks, 15_000);
    return () => clearInterval(iv);
  }, [setup, refreshTasks]);

  useEffect(() => {
    if (!setup) {
      progressSubscriptionsRef.current.forEach((unsubscribe) => unsubscribe());
      progressSubscriptionsRef.current.clear();
      return;
    }

    const analyzingIds = new Set(
      tasks.filter((task) => textValue(task.fields?.状态) === '分析中').map((task) => task.record_id),
    );

    for (const [recordId, unsubscribe] of progressSubscriptionsRef.current) {
      if (!analyzingIds.has(recordId)) {
        unsubscribe();
        progressSubscriptionsRef.current.delete(recordId);
      }
    }

    analyzingIds.forEach((recordId) => {
      if (progressSubscriptionsRef.current.has(recordId)) return;
      const unsubscribe = subscribeTaskProgress(recordId, (event: ProgressEvent) => {
        setLiveEvents((prev) => ({
          ...prev,
          [event.task_id]: {
            taskId: event.task_id,
            stage: String(event.payload.stage || event.event_type),
            progress: typeof event.payload.progress === 'number' ? event.payload.progress : 0,
            status:
              event.event_type === 'task.done'
                ? 'done'
                : event.event_type === 'task.error'
                  ? 'error'
                  : 'running',
            updatedAt: event.ts,
          },
        }));
      });
      progressSubscriptionsRef.current.set(recordId, unsubscribe);
    });
  }, [setup, tasks]);

  useEffect(
    () => () => {
      progressSubscriptionsRef.current.forEach((unsubscribe) => unsubscribe());
      progressSubscriptionsRef.current.clear();
    },
    [],
  );

  const handleSetup = async () => {
    setLoading(true);
    try {
      const response = await setupWorkflow(setupName.trim() || '内容运营虚拟组织', {
        mode: setupMode,
        base_type: setupBaseType,
        apply_native: setupApplyNative,
      });
      setSetupState(response);
      toast({ title: '多维表格创建成功', description: response.url });
    } catch (err) {
      toast({ title: '创建失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleStart = async () => {
    if (!setup) return;
    setLoading(true);
    try {
      await startWorkflow(setup.app_token, setup.table_ids);
      setRunning(true);
      toast({ title: '调度器已启动', description: '七岗协作已进入轮询模式' });
    } catch (err) {
      toast({ title: '启动失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleApplyNative = async () => {
    if (!setup) return;
    setLoading(true);
    try {
      const response = await applyNativeManifest();
      setSetupState((prev) =>
        prev
          ? {
              ...prev,
              native_assets: response.native_assets,
              native_manifest: response.native_manifest,
              native_apply_report: response.report,
            }
          : prev,
      );
      toast({ title: '原生化执行完成', description: '已尝试创建飞书 workflow / dashboard / role 等原生对象' });
    } catch (err) {
      toast({ title: '原生化执行失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopWorkflow();
      setRunning(false);
      toast({ title: '调度器已停止' });
    } catch (err) {
      toast({ title: '停止失败', description: String(err), variant: 'destructive' });
    } finally {
      setLoading(false);
    }
  };

  const handleSeed = async () => {
    if (!setup || !newTaskTitle.trim()) return;
    try {
      await seedTask(
        setup.app_token,
        setup.table_ids.task,
        newTaskTitle.trim(),
        '综合分析',
        newTaskBackground.trim(),
        {
          task_source: newTaskSource,
          business_owner: newTaskBusinessOwner,
          audience_level: newTaskAudienceLevel,
          target_audience: newTaskAudience.trim(),
          output_purpose: newTaskPurpose,
          success_criteria: newTaskSuccessCriteria.trim(),
          constraints: newTaskConstraints.trim(),
          business_stage: '增长爬坡',
          referenced_dataset: newTaskDatasetRef.trim(),
          template_name: textValue(
            activeTemplates.find((record) => record.record_id === selectedTemplateId)?.fields?.模板名称,
          ),
          report_audience: newTaskReportAudience.trim(),
          approval_owner: newTaskApprovalOwner.trim(),
          execution_owner: newTaskExecutionOwner.trim(),
          review_owner: newTaskReviewOwner.trim(),
          retrospective_owner: newTaskRetrospectiveOwner.trim(),
          review_sla_hours: Number(newTaskReviewSla) || undefined,
        },
      );
      setNewTaskTitle('');
      setNewTaskBackground('');
      setNewTaskAudience('');
      setNewTaskPurpose('经营诊断');
      setNewTaskSource('手工创建');
      setNewTaskBusinessOwner('综合经营');
      setNewTaskAudienceLevel('负责人');
      setNewTaskSuccessCriteria('');
      setNewTaskConstraints('');
      setNewTaskDatasetRef('');
      setNewTaskReportAudience('');
      setNewTaskApprovalOwner('');
      setNewTaskExecutionOwner('');
      setNewTaskReviewOwner('');
      setNewTaskRetrospectiveOwner('');
      setNewTaskReviewSla('');
      setSelectedTemplateId('');
      toast({ title: '任务已写入', description: '调度器将在下一轮自动领取并生成决策产物' });
      refreshTasks();
    } catch (err) {
      toast({ title: '写入失败', description: String(err), variant: 'destructive' });
    }
  };

  const handleManagementConfirm = async (
    action: 'approve' | 'execute' | 'retrospective',
    successTitle: string,
    task: TaskRecord | null | undefined = selectedTask,
  ) => {
    if (!setup || !task) return;
    try {
      await confirmTaskWorkflow(setup.app_token, setup.table_ids.task, task.record_id, action);
      toast({ title: successTitle, description: '已回写到分析任务主表' });
      setSelectedTaskId(task.record_id);
      refreshTasks();
    } catch (err) {
      toast({ title: '回写失败', description: String(err), variant: 'destructive' });
    }
  };

  const prioritizedTasks = useMemo(() => {
    return [...tasks].sort((left, right) => {
      const leftRank = STATUS_ORDER.indexOf((textValue(left.fields?.状态) || '待分析') as (typeof STATUS_ORDER)[number]);
      const rightRank = STATUS_ORDER.indexOf((textValue(right.fields?.状态) || '待分析') as (typeof STATUS_ORDER)[number]);
      if (leftRank !== rightRank) return leftRank - rightRank;
      const scoreDelta = numberValue(right.fields?.综合评分) - numberValue(left.fields?.综合评分);
      if (scoreDelta !== 0) return scoreDelta;
      return recordTimestamp(right, ['最近更新', '创建时间']) - recordTimestamp(left, ['最近更新', '创建时间']);
    });
  }, [tasks]);

  const highlightedTask = prioritizedTasks[0] || null;

  useEffect(() => {
    if (!tasks.length) {
      setSelectedTaskId('');
      return;
    }
    if (selectedTaskId && tasks.some((task) => task.record_id === selectedTaskId)) return;
    setSelectedTaskId(highlightedTask?.record_id || tasks[0].record_id);
  }, [tasks, selectedTaskId, highlightedTask]);

  const selectedTask =
    tasks.find((task) => task.record_id === selectedTaskId) || highlightedTask || null;
  const selectedLive = selectedTask ? liveEvents[selectedTask.record_id] : undefined;

  const latestReportByTitle = useMemo(
    () => buildLatestRecordMap(reportRecords, '报告标题', ['生成时间']),
    [reportRecords],
  );
  const latestReviewByTitle = useMemo(
    () => buildLatestRecordMap(reviewRecords, '任务标题', ['生成时间']),
    [reviewRecords],
  );
  const evidenceByTitle = useMemo(
    () => buildGroupedRecordMap(evidenceRecords, '任务标题', ['生成时间']),
    [evidenceRecords],
  );
  const actionByTitle = useMemo(
    () => buildGroupedRecordMap(actionRecords, '任务标题', ['生成时间']),
    [actionRecords],
  );
  const reviewHistoryByTitle = useMemo(
    () => buildGroupedRecordMap(reviewHistoryRecords, '任务标题', ['生成时间']),
    [reviewHistoryRecords],
  );
  const archiveByTitle = useMemo(
    () => buildGroupedRecordMap(archiveRecords, '任务标题', ['生成时间']),
    [archiveRecords],
  );
  const automationLogByTitle = useMemo(
    () => buildGroupedRecordMap(automationLogRecords, '任务标题', ['生成时间']),
    [automationLogRecords],
  );
  const activeTemplates = useMemo(
    () => templateRecords.filter((record) => booleanValue(record.fields?.启用)),
    [templateRecords],
  );
  useEffect(() => {
    if (!selectedTemplateId) return;
    if (activeTemplates.some((record) => record.record_id === selectedTemplateId)) return;
    setSelectedTemplateId('');
  }, [activeTemplates, selectedTemplateId]);

  const summary = useMemo(() => {
    const counts: Record<string, number> = {};
    tasks.forEach((task) => {
      const status = textValue(task.fields?.状态) || '未知';
      counts[status] = (counts[status] || 0) + 1;
    });
    return counts;
  }, [tasks]);

  const insightStats = useMemo(() => {
    const pending = summary['待分析'] || 0;
    const runningCount = summary['分析中'] || 0;
    const completed = summary['已完成'] || 0;
    const archived = summary['已归档'] || 0;
    const total = tasks.length;
    const closureRate = total > 0 ? Math.round(((completed + archived) / total) * 100) : 0;
    return { pending, runningCount, completed, archived, total, closureRate };
  }, [summary, tasks.length]);

  const reviewOverview = useMemo(() => {
    let directAdopt = 0;
    let recheck = 0;
    let rerun = 0;
    tasks.forEach((task) => {
      const recommend = taskReviewAction(task, latestReviewByTitle.get(taskTitle(task)) || null);
      if (recommend === '直接采用') directAdopt += 1;
      if (recommend === '补数后复核') recheck += 1;
      if (recommend === '建议重跑') rerun += 1;
    });
    return { directAdopt, recheck, rerun };
  }, [latestReviewByTitle, tasks]);

  const evidenceOverview = useMemo(() => {
    let highConfidence = 0;
    let hardEvidence = 0;
    let ceoLinked = 0;
    evidenceRecords.forEach((record) => {
      if (textValue(record.fields?.证据置信度) === 'high') highConfidence += 1;
      if (textValue(record.fields?.证据等级) === '硬证据') hardEvidence += 1;
      if (booleanValue(record.fields?.进入CEO汇总)) ceoLinked += 1;
    });
    return { highConfidence, hardEvidence, ceoLinked };
  }, [evidenceRecords]);

  const actionOverview = useMemo(() => {
    let completed = 0;
    let skipped = 0;
    let failed = 0;
    actionRecords.forEach((record) => {
      const status = textValue(record.fields?.动作状态);
      if (status === '已完成') completed += 1;
      if (status === '已跳过') skipped += 1;
      if (status === '执行失败') failed += 1;
    });
    return { completed, skipped, failed, total: actionRecords.length };
  }, [actionRecords]);

  const automationOverview = useMemo(() => {
    let completed = 0;
    let skipped = 0;
    let failed = 0;
    automationLogRecords.forEach((record) => {
      const status = textValue(record.fields?.执行状态);
      if (status === '已完成') completed += 1;
      if (status === '已跳过') skipped += 1;
      if (status === '执行失败') failed += 1;
    });
    return { completed, skipped, failed, total: automationLogRecords.length };
  }, [automationLogRecords]);

  const managementOverview = useMemo(() => {
    let pendingApproval = 0;
    let approved = 0;
    let pendingExecution = 0;
    let executed = 0;
    let inRetrospective = 0;
    tasks.forEach((task) => {
      const route = taskWorkflowRoute(task);
      const approvedFlag = booleanValue(task.fields?.是否已拍板);
      const executedFlag = booleanValue(task.fields?.是否已执行落地);
      const retroFlag = booleanValue(task.fields?.是否进入复盘);
      if (route === '等待拍板' && !approvedFlag) pendingApproval += 1;
      if (approvedFlag) approved += 1;
      if (route === '直接执行' && !executedFlag) pendingExecution += 1;
      if (executedFlag) executed += 1;
      if (retroFlag) inRetrospective += 1;
    });
    return { pendingApproval, approved, pendingExecution, executed, inRetrospective };
  }, [tasks]);
  const roleWorkspace = useMemo(() => {
    const approval = sortTasksByLatest(
      tasks.filter((task) => taskResponsibilityRole(task) === '拍板人'),
    );
    const execution = sortTasksByLatest(
      tasks.filter((task) => taskResponsibilityRole(task) === '执行人'),
    );
    const review = sortTasksByLatest(tasks.filter((task) => taskResponsibilityRole(task) === '复核人'));
    const retrospective = sortTasksByLatest(
      tasks.filter((task) => taskResponsibilityRole(task) === '复盘负责人'),
    );
    return { approval, execution, review, retrospective };
  }, [tasks]);
  const exceptionWorkspace = useMemo(() => {
    const approvalStale = sortTasksByLatest(
      tasks.filter((task) => taskExceptionType(task) === '拍板滞留'),
    );
    const executionOverdue = sortTasksByLatest(
      tasks.filter((task) => taskExceptionType(task) === '执行超期'),
    );
    const reviewOverdue = sortTasksByLatest(
      tasks.filter((task) => taskExceptionType(task) === '复核超时'),
    );
    const retrospectiveStale = sortTasksByLatest(
      tasks.filter((task) => taskExceptionType(task) === '复盘滞留'),
    );
    return { approvalStale, executionOverdue, reviewOverdue, retrospectiveStale };
  }, [tasks]);

  const templateOverview = useMemo(() => {
    const byRoute: Record<string, number> = {};
    activeTemplates.forEach((record) => {
      const route = textValue(record.fields?.适用工作流路由) || '未标注';
      byRoute[route] = (byRoute[route] || 0) + 1;
    });
    return {
      total: activeTemplates.length,
      byRoute,
    };
  }, [activeTemplates]);

  const selectedTitle = taskTitle(selectedTask);
  const selectedReport = selectedTitle ? latestReportByTitle.get(selectedTitle) || null : null;
  const selectedReview = selectedTitle ? latestReviewByTitle.get(selectedTitle) || null : null;
  const selectedEvidence = useMemo(
    () => (selectedTitle ? evidenceByTitle.get(selectedTitle) || [] : []),
    [evidenceByTitle, selectedTitle],
  );
  const selectedActions = useMemo(
    () => (selectedTitle ? (actionByTitle.get(selectedTitle) || []).slice(0, 8) : []),
    [actionByTitle, selectedTitle],
  );
  const selectedReviewHistory = useMemo(
    () => (selectedTitle ? (reviewHistoryByTitle.get(selectedTitle) || []).slice(0, 6) : []),
    [reviewHistoryByTitle, selectedTitle],
  );
  const selectedArchiveRecords = useMemo(
    () => (selectedTitle ? (archiveByTitle.get(selectedTitle) || []).slice(0, 6) : []),
    [archiveByTitle, selectedTitle],
  );
  const selectedAutomationLogs = useMemo(
    () => (selectedTitle ? (automationLogByTitle.get(selectedTitle) || []).slice(0, 8) : []),
    [automationLogByTitle, selectedTitle],
  );
  const templateSuggestions = useMemo(
    () =>
      activeTemplates.filter((record) => {
        const purpose = textValue(record.fields?.适用输出目的);
        return !purpose || purpose === newTaskPurpose;
      }),
    [activeTemplates, newTaskPurpose],
  );
  const selectedTemplate = useMemo(
    () => activeTemplates.find((record) => record.record_id === selectedTemplateId) || null,
    [activeTemplates, selectedTemplateId],
  );
  const templateRouteChips = useMemo(
    () =>
      Object.entries(templateOverview.byRoute)
        .sort((left, right) => right[1] - left[1])
        .slice(0, 4),
    [templateOverview],
  );
  const nativeFormBlueprints = objectList(setup?.native_assets?.form_blueprints);
  const nativeAutomationTemplates = objectList(setup?.native_assets?.automation_templates);
  const nativeWorkflowBlueprints = objectList(setup?.native_assets?.workflow_blueprints);
  const nativeDashboardBlueprints = objectList(setup?.native_assets?.dashboard_blueprints);
  const nativeRoleBlueprints = objectList(setup?.native_assets?.role_blueprints);
  const nativeAssetGroups = Array.isArray(setup?.native_assets?.asset_groups)
    ? setup?.native_assets?.asset_groups || []
    : [];
  const nativeChecklist = objectList(setup?.native_assets?.manual_finish_checklist);
  const nativeAssetCounts = setup?.native_assets?.status_summary?.counts || {};
  const nativeInstallOrder = objectList(setup?.native_manifest?.install_order);
  const nativeCommandPacks = objectList(setup?.native_manifest?.command_packs);
  const nativeApplyReport = objectList(setup?.native_apply_report);
  const selectedTaskNumber = textValue(taskField(selectedTask, '任务编号'));
  const selectedProgress = selectedLive
    ? Math.max(safeProgress(taskField(selectedTask, '进度')), selectedLive.progress * 100)
    : safeProgress(taskField(selectedTask, '进度'));

  const selectedSummaryText =
    textValue(selectedTask?.fields?.最新管理摘要) ||
    textValue(selectedReport?.fields?.管理摘要) ||
    textValue(selectedTask?.fields?.最新评审摘要) ||
    textValue(selectedReview?.fields?.评审摘要) ||
    textValue(taskField(selectedTask, '背景说明')) ||
    '当前任务尚未形成综合摘要，等待调度器完成分析与评审。';
  const selectedOneLiner =
    textValue(selectedReport?.fields?.一句话结论) ||
    textValue(selectedTask?.fields?.最新管理摘要) ||
    selectedSummaryText;
  const selectedExecBrief =
    textValue(selectedReport?.fields?.高管一页纸) ||
    `一句话结论：${selectedOneLiner}\n\n管理摘要：${selectedSummaryText}`;

  const selectedDecisionColumns = [
    { title: '必须拍板', items: splitListText(selectedReport?.fields?.必须拍板事项), tone: 'text-rose-700' },
    { title: '可授权推进', items: splitListText(selectedReport?.fields?.可授权事项), tone: 'text-sky-700' },
    { title: '需补数', items: splitListText(selectedReport?.fields?.需补数事项 || selectedReview?.fields?.需补数事项), tone: 'text-amber-700' },
    { title: '立即执行', items: splitListText(selectedReport?.fields?.立即执行事项), tone: 'text-emerald-700' },
  ];

  const selectedReviewScores = [
    { label: '真实性', value: clampScore(selectedReview?.fields?.真实性) },
    { label: '决策性', value: clampScore(selectedReview?.fields?.决策性) },
    { label: '可执行性', value: clampScore(selectedReview?.fields?.可执行性) },
    { label: '闭环准备度', value: clampScore(selectedReview?.fields?.闭环准备度) },
  ];

  const selectedEvidenceOverview = useMemo(() => {
    let hard = 0;
    let inferred = 0;
    let pending = 0;
    selectedEvidence.forEach((record) => {
      const grade = textValue(record.fields?.证据等级);
      if (grade === '硬证据') hard += 1;
      if (grade === '推断') inferred += 1;
      if (grade === '待验证') pending += 1;
    });
    return { hard, inferred, pending };
  }, [selectedEvidence]);

  const selectedManagementFlags = [
    {
      label: '是否已拍板',
      value: yesNoLabel(selectedTask?.fields?.是否已拍板),
      note: textValue(selectedTask?.fields?.拍板人) || '待回写拍板人',
      tone: booleanValue(selectedTask?.fields?.是否已拍板)
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
        : 'border-rose-200 bg-rose-50 text-rose-700',
    },
    {
      label: '是否已执行落地',
      value: yesNoLabel(selectedTask?.fields?.是否已执行落地),
      note: formatDateValue(selectedTask?.fields?.执行完成时间),
      tone: booleanValue(selectedTask?.fields?.是否已执行落地)
        ? 'border-sky-200 bg-sky-50 text-sky-700'
        : 'border-amber-200 bg-amber-50 text-amber-700',
    },
    {
      label: '是否进入复盘',
      value: yesNoLabel(selectedTask?.fields?.是否进入复盘),
      note: textValue(selectedTask?.fields?.归档状态) || '未进入复盘流程',
      tone: booleanValue(selectedTask?.fields?.是否进入复盘)
        ? 'border-violet-200 bg-violet-50 text-violet-700'
        : 'border-slate-200 bg-slate-100 text-slate-600',
    },
  ];

  const selectedFollowups = useMemo(() => {
    if (!selectedTask) return [];
    return tasks
      .filter((task) => {
        if (task.record_id === selectedTask.record_id) return false;
        return (
          taskDependsOn(task, selectedTaskNumber) ||
          textValue(task.fields?.背景说明).includes(selectedTitle)
        );
      })
      .sort((left, right) => recordTimestamp(right, ['最近更新', '创建时间']) - recordTimestamp(left, ['最近更新', '创建时间']))
      .slice(0, 6);
  }, [selectedTask, selectedTaskNumber, selectedTitle, tasks]);

  const taskSwitcher = prioritizedTasks.slice(0, 6);

  const liveFeed = useMemo(
    () =>
      Object.values(liveEvents)
        .sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime())
        .slice(0, 6),
    [liveEvents],
  );

  const portfolioMetrics = [
    {
      label: '任务总量',
      value: insightStats.total,
      note: '工作流资产池',
      icon: Briefcase,
      surface: 'from-slate-100 via-white to-slate-50',
      accent: 'text-slate-900',
    },
    {
      label: '直接采用',
      value: reviewOverview.directAdopt,
      note: '评审通过后可直接汇报',
      icon: CheckCircle2,
      surface: 'from-emerald-100 via-white to-cyan-50',
      accent: 'text-emerald-700',
    },
    {
      label: '待复核',
      value: reviewOverview.recheck + reviewOverview.rerun,
      note: '补数或建议重跑',
      icon: ShieldAlert,
      surface: 'from-amber-100 via-white to-orange-50',
      accent: 'text-amber-700',
    },
    {
      label: '硬证据',
      value: evidenceOverview.hardEvidence || evidenceOverview.highConfidence,
      note: '可直接支撑汇报结论的证据底座',
      icon: FileSearch,
      surface: 'from-sky-100 via-white to-indigo-50',
      accent: 'text-sky-700',
    },
    {
      label: '进入 CEO 汇总',
      value: evidenceOverview.ceoLinked,
      note: '被提升到机会、风险或决策层',
      icon: Layers3,
      surface: 'from-violet-100 via-white to-fuchsia-50',
      accent: 'text-violet-700',
    },
    {
      label: '闭环率',
      value: `${insightStats.closureRate}%`,
      note: '完成或归档占比',
      icon: Target,
      surface: 'from-rose-100 via-white to-orange-50',
      accent: 'text-rose-700',
    },
    {
      label: '交付动作',
      value: actionOverview.total,
      note: '汇报、执行、复核与自动跟进日志',
      icon: Flame,
      surface: 'from-cyan-100 via-white to-sky-50',
      accent: 'text-cyan-700',
    },
    {
      label: '失败动作',
      value: actionOverview.failed,
      note: '需要人工处理的异常交付动作',
      icon: ShieldAlert,
      surface: 'from-rose-100 via-white to-red-50',
      accent: 'text-rose-700',
    },
    {
      label: '自动化日志',
      value: automationOverview.total,
      note: '节点级审计与补救入口',
      icon: Activity,
      surface: 'from-amber-100 via-white to-yellow-50',
      accent: 'text-amber-700',
    },
    {
      label: '启用模板',
      value: templateOverview.total,
      note: '消息包、执行包与负责人默认值模板',
      icon: Sparkles,
      surface: 'from-violet-100 via-white to-fuchsia-50',
      accent: 'text-violet-700',
    },
    {
      label: '待拍板确认',
      value: managementOverview.pendingApproval,
      note: '等待管理层在主表回写拍板结果',
      icon: ShieldAlert,
      surface: 'from-rose-100 via-white to-orange-50',
      accent: 'text-rose-700',
    },
    {
      label: '待执行落地',
      value: managementOverview.pendingExecution,
      note: '已进入执行路由但尚未回写落地完成',
      icon: ArrowUpRight,
      surface: 'from-sky-100 via-white to-cyan-50',
      accent: 'text-sky-700',
    },
    {
      label: '进入复盘',
      value: managementOverview.inRetrospective,
      note: '已完成交付并进入复盘阶段的任务数',
      icon: RefreshCw,
      surface: 'from-violet-100 via-white to-indigo-50',
      accent: 'text-violet-700',
    },
  ];

  const applyTemplate = useCallback((record: TaskRecord) => {
    setSelectedTemplateId(record.record_id);
    const fields = record.fields || {};
    const templatePurpose = textValue(fields.适用输出目的);
    if (templatePurpose && PURPOSE_OPTIONS.includes(templatePurpose as (typeof PURPOSE_OPTIONS)[number])) {
      setNewTaskPurpose(templatePurpose as (typeof PURPOSE_OPTIONS)[number]);
    }
    if (!newTaskReportAudience.trim()) {
      setNewTaskReportAudience(textValue(fields.默认汇报对象));
    }
    if (!newTaskApprovalOwner.trim()) {
      setNewTaskApprovalOwner(textValue(fields.默认拍板负责人));
    }
    if (!newTaskExecutionOwner.trim()) {
      setNewTaskExecutionOwner(textValue(fields.默认执行负责人));
    }
    if (!newTaskReviewOwner.trim()) {
      setNewTaskReviewOwner(textValue(fields.默认复核负责人));
    }
    if (!newTaskRetrospectiveOwner.trim()) {
      setNewTaskRetrospectiveOwner(textValue(fields.默认复盘负责人));
    }
    if (!newTaskReviewSla.trim() && numberValue(fields.默认复核SLA小时) > 0) {
      setNewTaskReviewSla(String(numberValue(fields.默认复核SLA小时)));
    }
    if (!newTaskAudience.trim() && textValue(fields.默认汇报对象)) {
      setNewTaskAudience(textValue(fields.默认汇报对象));
    }
  }, [newTaskApprovalOwner, newTaskAudience, newTaskExecutionOwner, newTaskReportAudience, newTaskRetrospectiveOwner, newTaskReviewOwner, newTaskReviewSla]);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(15,118,110,0.12),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(14,165,233,0.14),_transparent_24%),radial-gradient(circle_at_bottom_right,_rgba(244,63,94,0.08),_transparent_22%),linear-gradient(180deg,_rgba(255,255,255,0.88),_rgba(242,243,245,1))] px-4 py-6 md:px-6 lg:px-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <section className="overflow-hidden rounded-[32px] border border-white/60 bg-white/88 shadow-[0_28px_100px_rgba(15,23,42,0.08)] backdrop-blur">
          <div className="grid gap-0 lg:grid-cols-[1.35fr_0.95fr]">
            <div className="relative overflow-hidden border-b border-slate-100 p-6 lg:border-b-0 lg:border-r lg:p-8">
              <div className="absolute inset-0 bg-[linear-gradient(140deg,rgba(15,118,110,0.12),rgba(14,165,233,0.08)_38%,transparent_62%)]" />
              <div className="relative flex flex-col gap-6">
                <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.26em] text-slate-500">
                  <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-emerald-700">Feishu Delivery Loop</span>
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">Decision Dossier</span>
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">Evidence First</span>
                </div>
                <div className="max-w-3xl space-y-3">
                  <h1 className="font-serif text-3xl font-semibold tracking-tight text-slate-950 md:text-5xl">
                    飞书多维表格多 Agent 交付驾驶舱
                  </h1>
                  <p className="max-w-2xl text-sm leading-7 text-slate-600 md:text-[15px]">
                    核心目标不是“跑完七个 Agent”，而是让每条分析任务在飞书里最终沉淀成
                    可汇报的 CEO 决策单、可追溯的证据链、可执行的下一步和可复核的再流转闭环。
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    { label: 'Wave 1', text: '五岗并行拆题，先把问题空间和机会面拉开。', icon: Sparkles },
                    { label: 'Wave 2', text: '财务顾问补足单位经济学、预算边界和风险约束。', icon: Flame },
                    { label: 'Wave 3', text: 'CEO 助理把结论压缩成拍板项、授权项和补数项。', icon: ArrowUpRight },
                  ].map((item) => {
                    const Icon = item.icon;
                    return (
                      <div key={item.label} className="rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm">
                        <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
                          <Icon className="h-4 w-4 text-teal-600" />
                          {item.label}
                        </div>
                        <p className="mt-2 text-sm leading-6 text-slate-600">{item.text}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="flex flex-col justify-between gap-5 p-6 lg:p-8">
              <div className="rounded-[28px] border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.96))] p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Workflow Control</p>
                    <h2 className="mt-2 text-xl font-semibold text-slate-950">运行总控台</h2>
                  </div>
                  <div className={`rounded-full px-3 py-1 text-xs font-medium ${running ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                    {running ? '运行中' : '已停止'}
                  </div>
                </div>
                <div className="mt-5 flex flex-wrap gap-3">
                  {!setup ? (
                    <Button onClick={handleSetup} disabled={loading} className="h-10 rounded-full px-5">
                      {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Database className="mr-2 h-4 w-4" />}
                      初始化多维表格
                    </Button>
                  ) : running ? (
                    <Button variant="outline" onClick={handleStop} disabled={loading} className="h-10 rounded-full px-5">
                      <Pause className="mr-2 h-4 w-4" /> 停止调度
                    </Button>
                  ) : (
                    <Button onClick={handleStart} disabled={loading} className="h-10 rounded-full px-5">
                      <Play className="mr-2 h-4 w-4" /> 启动调度
                    </Button>
                  )}
                  <Button variant="ghost" onClick={refreshTasks} disabled={!setup} className="h-10 rounded-full px-4">
                    <RefreshCw className="mr-2 h-4 w-4" /> 刷新
                  </Button>
                  {setup && (
                    <Button variant="outline" onClick={handleApplyNative} disabled={loading} className="h-10 rounded-full px-5">
                      <Sparkles className="mr-2 h-4 w-4" /> 一键原生化
                    </Button>
                  )}
                </div>
                <div className="mt-5 grid gap-3 rounded-2xl border border-slate-200 bg-white/88 p-4">
                  <Input
                    value={setupName}
                    onChange={(e) => setSetupName(e.target.value)}
                    placeholder="Base 名称"
                    className="h-11 rounded-2xl border-slate-200 bg-slate-50/80"
                  />
                  <div className="grid gap-3 md:grid-cols-2">
                    <Select value={setupMode} onValueChange={(value) => setSetupMode(value as (typeof SETUP_MODE_OPTIONS)[number])}>
                      <SelectTrigger className="h-11 rounded-2xl border-slate-200 bg-slate-50/80">
                        <SelectValue placeholder="初始化模式" />
                      </SelectTrigger>
                      <SelectContent>
                        {SETUP_MODE_OPTIONS.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select value={setupBaseType} onValueChange={(value) => setSetupBaseType(value as (typeof BASE_TYPE_OPTIONS)[number])}>
                      <SelectTrigger className="h-11 rounded-2xl border-slate-200 bg-slate-50/80">
                        <SelectValue placeholder="Base 类型" />
                      </SelectTrigger>
                      <SelectContent>
                        {BASE_TYPE_OPTIONS.map((option) => (
                          <SelectItem key={option} value={option}>
                            {option}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="grid gap-2 text-xs text-slate-500 md:grid-cols-2">
                    <div>`seed_demo`：建完整演示 Base，直接带种子任务和数据源。</div>
                    <div>`prod_empty`：建生产空 Base，只保留结构、模板和原生资产。</div>
                    <div>`template_only`：建模板 Base，适合复制出多个业务交付空间。</div>
                    <div>`validation / production / template`：明确这份 Base 的用途和验收口径。</div>
                  </div>
                  <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={setupApplyNative}
                      onChange={(e) => setSetupApplyNative(e.target.checked)}
                      className="h-4 w-4 rounded border-slate-300"
                    />
                    setup 后立即尝试创建飞书原生 workflow / dashboard / role
                  </label>
                </div>
                {setup ? (
                  <div className="mt-5 space-y-3 rounded-2xl border border-slate-200 bg-white/85 p-4 text-sm">
                    <a
                      href={setup.url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-teal-700 hover:text-teal-900"
                    >
                      打开飞书多维表格 <ArrowUpRight className="h-3.5 w-3.5" />
                    </a>
                    <div className="grid gap-2 text-xs text-slate-500">
                      <div>主链路：`分析任务 / 岗位分析 / 综合报告 / 数字员工效能`</div>
                      <div>增强层：`数据源库 / 证据链 / 产出评审`</div>
                      <div className="truncate">app_token: {setup.app_token}</div>
                    </div>
                  </div>
                ) : (
                  <p className="mt-5 text-sm leading-6 text-slate-600">
                    初始化后会自动创建任务主表、证据链表、评审表和汇报视图，后续所有交付物都会在这条结构里闭环。
                  </p>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {[
                  { label: '待分析', value: insightStats.pending, hint: '待领取', icon: Clock3 },
                  { label: '分析中', value: insightStats.runningCount, hint: '协同中', icon: Activity },
                  { label: '已完成', value: insightStats.completed, hint: '可汇报', icon: CheckCircle2 },
                ].map((item) => {
                  const Icon = item.icon;
                  return (
                    <div key={item.label} className="rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
                      <div className="flex items-center justify-between">
                        <span className="text-xs uppercase tracking-[0.2em] text-slate-500">{item.label}</span>
                        <Icon className="h-4 w-4 text-slate-400" />
                      </div>
                      <div className="mt-3 text-2xl font-semibold text-slate-950">{item.value}</div>
                      <div className="mt-1 text-xs text-slate-500">{item.hint}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </section>

        {setup && (
          <>
            <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {portfolioMetrics.map((metric) => {
                const Icon = metric.icon;
                return (
                  <div
                    key={metric.label}
                    className="rounded-[24px] border border-white/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(255,255,255,0.82))] p-5 shadow-[0_18px_48px_rgba(15,23,42,0.06)]"
                  >
                    <div className={`rounded-2xl bg-gradient-to-br ${metric.surface} p-4`}>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">{metric.label}</p>
                          <div className={`mt-3 text-3xl font-semibold ${metric.accent}`}>{metric.value}</div>
                        </div>
                        <div className="rounded-2xl border border-white/70 bg-white/80 p-3 shadow-sm">
                          <Icon className={`h-5 w-5 ${metric.accent}`} />
                        </div>
                      </div>
                      <p className="mt-4 text-sm text-slate-600">{metric.note}</p>
                    </div>
                  </div>
                );
              })}
            </section>

            <section className="rounded-[30px] border border-white/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(245,247,250,0.96))] p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Native Assets</p>
                  <h2 className="mt-2 font-serif text-3xl font-semibold text-slate-950">飞书原生交付资产包</h2>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                    这里展示当前 Base 已经准备好的原生表单、自动化、工作流、仪表盘和角色蓝图。目标不是让前端代替飞书，而是让飞书本身成为真正的交付操作面。
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-slate-600">
                  {setup?.native_assets?.overall_state && (
                    <span className={`rounded-full border px-3 py-1 ${ASSET_STATE_STYLE[setup.native_assets.overall_state] || 'border-slate-200 bg-white text-slate-600'}`}>
                      当前落地状态：{ASSET_STATE_LABEL[setup.native_assets.overall_state] || setup.native_assets.overall_state}
                    </span>
                  )}
                  {setup?.base_meta?.base_type && (
                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                      Base 类型：{setup.base_meta.base_type}
                    </span>
                  )}
                  {setup?.base_meta?.mode && (
                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                      初始化模式：{setup.base_meta.mode}
                    </span>
                  )}
                  {setup?.base_meta?.schema_version && (
                    <span className="rounded-full border border-slate-200 bg-white px-3 py-1">
                      Schema：{setup.base_meta.schema_version}
                    </span>
                  )}
                </div>
              </div>

              <div className="mt-6 grid gap-4 xl:grid-cols-5">
                {[
                  { label: '已创建', value: nativeAssetCounts.created || 0, note: '已经在 Base 中真正落下来的原生资产', icon: CheckCircle2, surface: 'from-emerald-100 via-white to-cyan-50', accent: 'text-emerald-700' },
                  { label: '待人工补完', value: nativeAssetCounts.manual_finish_required || 0, note: '还差共享、启用或最后一步配置', icon: ShieldAlert, surface: 'from-amber-100 via-white to-orange-50', accent: 'text-amber-700' },
                  { label: '蓝图就绪', value: nativeAssetCounts.blueprint_ready || 0, note: '字段契约和落地说明已准备好', icon: Layers3, surface: 'from-violet-100 via-white to-indigo-50', accent: 'text-violet-700' },
                  { label: '表单入口', value: nativeFormBlueprints.length, note: nativeFormBlueprints[0]?.shared_url ? '已形成收集入口' : '仍需补共享链接', icon: Database, surface: 'from-cyan-100 via-white to-sky-50', accent: 'text-cyan-700' },
                  { label: '自动化 / 工作流', value: nativeAutomationTemplates.length + nativeWorkflowBlueprints.length, note: '围绕主表字段和路由条件组织', icon: Sparkles, surface: 'from-rose-100 via-white to-orange-50', accent: 'text-rose-700' },
                ].map((metric) => {
                  const Icon = metric.icon;
                  return (
                    <div key={metric.label} className="rounded-[24px] border border-white/70 bg-white p-4 shadow-sm">
                      <div className={`rounded-2xl bg-gradient-to-br ${metric.surface} p-4`}>
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">{metric.label}</p>
                            <div className={`mt-3 text-3xl font-semibold ${metric.accent}`}>{metric.value}</div>
                          </div>
                          <div className="rounded-2xl border border-white/70 bg-white/80 p-3 shadow-sm">
                            <Icon className={`h-5 w-5 ${metric.accent}`} />
                          </div>
                        </div>
                        <p className="mt-3 text-sm leading-6 text-slate-600">{metric.note}</p>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-6 grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
                <div className="rounded-[24px] border border-slate-200 bg-white/92 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Readiness Matrix</div>
                      <div className="mt-2 text-xl font-semibold text-slate-950">原生资产落地矩阵</div>
                    </div>
                    <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                      共 {setup?.native_assets?.status_summary?.total_assets || 0} 项
                    </div>
                  </div>
                  <div className="mt-4 space-y-3">
                    {nativeAssetGroups.map((group) => (
                      <div key={group.key} className="rounded-[20px] border border-slate-200 bg-slate-50/80 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-slate-950">{group.label}</div>
                            <div className="mt-1 text-xs text-slate-500">{group.count} 项原生资产</div>
                          </div>
                          <div className={`rounded-full border px-3 py-1 text-xs font-medium ${ASSET_STATE_STYLE[group.state] || 'border-slate-200 bg-white text-slate-600'}`}>
                            {ASSET_STATE_LABEL[group.state] || group.state}
                          </div>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
                          {Object.entries(group.counts || {})
                            .filter(([, count]) => Number(count) > 0)
                            .map(([state, count]) => (
                              <span
                                key={state}
                                className={`rounded-full border px-2.5 py-1 ${ASSET_STATE_STYLE[state] || 'border-slate-200 bg-white text-slate-600'}`}
                              >
                                {ASSET_STATE_LABEL[state] || state} {count}
                              </span>
                            ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-[24px] border border-slate-200 bg-white/92 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Native Checklist</div>
                      <div className="mt-2 text-xl font-semibold text-slate-950">飞书内补完清单</div>
                    </div>
                    <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                      直接按这份清单做验收
                    </div>
                  </div>
                  <div className="mt-4 space-y-3">
                    {nativeChecklist.length === 0 ? (
                      <EmptyState text="当前没有可展示的补完清单。" />
                    ) : (
                      nativeChecklist.map((item) => {
                        const state = textValue(item.state) || 'blueprint_ready';
                        return (
                          <div key={textValue(item.name)} className="rounded-[20px] border border-slate-200 bg-slate-50/80 p-4">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <div className="text-sm font-semibold text-slate-950">{textValue(item.name)}</div>
                                <div className="mt-1 text-xs text-slate-500">
                                  {textValue(item.surface)} · 负责人 {textValue(item.owner) || '待指定'}
                                </div>
                              </div>
                              <div className={`rounded-full border px-3 py-1 text-xs font-medium ${booleanValue(item.done) ? ASSET_STATE_STYLE.created : ASSET_STATE_STYLE[state] || 'border-slate-200 bg-white text-slate-600'}`}>
                                {booleanValue(item.done) ? '已就绪' : ASSET_STATE_LABEL[state] || state}
                              </div>
                            </div>
                            <div className="mt-3 text-sm leading-6 text-slate-700">{textValue(item.step)}</div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-6 rounded-[24px] border border-slate-200 bg-[linear-gradient(135deg,rgba(15,23,42,0.02),rgba(255,255,255,0.98),rgba(8,145,178,0.05))] p-5">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Native Install Pack</div>
                    <div className="mt-2 text-xl font-semibold text-slate-950">飞书原生安装命令包</div>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                      这部分不是说明文，而是按 `lark-cli base` 组织的原生安装顺序和命令模板。它的作用是把当前蓝图继续推进成飞书云侧真实对象。
                    </p>
                  </div>
                  <div className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600">
                    manifest {textValue(setup?.native_manifest?.manifest_version) || 'v1'}
                  </div>
                </div>

                <div className="mt-5 grid gap-4 xl:grid-cols-[0.78fr_1.22fr]">
                  <div className="rounded-[22px] border border-slate-200 bg-white/92 p-4">
                    <div className="text-sm font-semibold text-slate-950">安装顺序</div>
                    <div className="mt-4 space-y-3">
                      {nativeInstallOrder.length === 0 ? (
                        <EmptyState text="当前没有可展示的安装顺序。" />
                      ) : (
                        nativeInstallOrder.map((item) => (
                          <div key={`${textValue(item.step)}-${textValue(item.title)}`} className="rounded-[18px] border border-slate-200 bg-slate-50/80 p-4">
                            <div className="flex items-center gap-3">
                              <div className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-950 text-xs font-semibold text-white">
                                {textValue(item.step)}
                              </div>
                              <div className="text-sm font-semibold text-slate-950">{textValue(item.title)}</div>
                            </div>
                            <div className="mt-2 text-sm leading-6 text-slate-600">{textValue(item.why)}</div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="space-y-4">
                    {nativeCommandPacks.length === 0 ? (
                      <EmptyState text="当前没有可展示的命令包。" />
                    ) : (
                      nativeCommandPacks.map((pack) => {
                        const status = textValue(pack.status) || 'blueprint_ready';
                        const commands = Array.isArray(pack.commands) ? (pack.commands as unknown[]) : [];
                        const notes = Array.isArray(pack.notes) ? (pack.notes as unknown[]) : [];
                        return (
                          <div key={textValue(pack.key) || textValue(pack.label)} className="rounded-[22px] border border-slate-200 bg-white/92 p-4 shadow-sm">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <div className="text-sm font-semibold text-slate-950">{textValue(pack.label)}</div>
                                <div className="mt-1 text-xs text-slate-500">{textValue(pack.surface)} 原生能力</div>
                              </div>
                              <div className={`rounded-full border px-3 py-1 text-xs font-medium ${ASSET_STATE_STYLE[status] || 'border-slate-200 bg-white text-slate-600'}`}>
                                {ASSET_STATE_LABEL[status] || status}
                              </div>
                            </div>
                            <div className="mt-4 rounded-[18px] border border-slate-200 bg-slate-950 p-4 text-[12px] leading-6 text-slate-100">
                              <pre className="whitespace-pre-wrap font-mono">
                                {commands.map((command) => String(command || '')).join('\n')}
                              </pre>
                            </div>
                            {notes.length > 0 && (
                              <div className="mt-4 flex flex-wrap gap-2">
                                {notes.map((note) => (
                                  <span key={String(note)} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                                    {String(note)}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </div>

              <div className="mt-6 rounded-[24px] border border-slate-200 bg-white/92 p-5">
                <div className="flex flex-wrap items-end justify-between gap-4">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Native Apply Report</div>
                    <div className="mt-2 text-xl font-semibold text-slate-950">原生化执行报告</div>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                      这里展示最近一次原生化执行的逐项结果，不再只看蓝图状态，而是看哪些对象真的创建了、哪些被跳过、哪些仍被权限或产品边界卡住。
                    </p>
                  </div>
                  <div className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
                    {nativeApplyReport.length > 0 ? `最近执行 ${nativeApplyReport.length} 项` : '尚未执行'}
                  </div>
                </div>
                <div className="mt-5 grid gap-4 xl:grid-cols-2">
                  {nativeApplyReport.length === 0 ? (
                    <div className="xl:col-span-2">
                      <EmptyState text="当前还没有原生化执行报告。可以在 setup 时勾选自动原生化，或点击“一键原生化”立即执行。" />
                    </div>
                  ) : (
                    nativeApplyReport.map((item) => {
                      const status = textValue(item.status) || 'manual_finish_required';
                      return (
                        <div key={`${textValue(item.surface)}-${textValue(item.name)}`} className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold text-slate-950">{textValue(item.name) || '未命名对象'}</div>
                              <div className="mt-1 text-xs text-slate-500">{textValue(item.surface)} 原生能力</div>
                            </div>
                            <div className={`rounded-full border px-3 py-1 text-xs font-medium ${APPLY_REPORT_STYLE[status] || 'border-slate-200 bg-white text-slate-600'}`}>
                              {status === 'created'
                                ? '已创建'
                                : status === 'skipped'
                                  ? '已跳过'
                                  : ASSET_STATE_LABEL[status] || status}
                            </div>
                          </div>
                          <div className="mt-3 grid gap-2 text-sm text-slate-700">
                            {textValue(item.object_id) && <div>对象 ID：{textValue(item.object_id)}</div>}
                            {typeof item.block_count === 'number' && Number(item.block_count) > 0 && <div>创建图表块：{String(item.block_count)}</div>}
                            {textValue(item.reason) && <div>跳过原因：{textValue(item.reason)}</div>}
                            {textValue(item.error) && <div className="text-rose-700">错误：{textValue(item.error)}</div>}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="mt-6 grid gap-4 xl:grid-cols-2">
                <div className="rounded-[24px] border border-slate-200 bg-white/90 p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Form Entry</div>
                      <div className="mt-2 text-xl font-semibold text-slate-950">多维表格原生入口</div>
                    </div>
                    <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                      {textValue(nativeFormBlueprints[0]?.status) || '待生成'}
                    </div>
                  </div>
                  <div className="mt-4 space-y-3 text-sm text-slate-700">
                    <div>入口表：`分析任务` → `📥 需求收集表`</div>
                    <div>字段契约：任务标题 / 输出目的 / 优先级 / 引用数据集 / 任务图像</div>
                    {textValue(nativeFormBlueprints[0]?.shared_url) ? (
                      <a
                        href={textValue(nativeFormBlueprints[0]?.shared_url)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 font-medium text-teal-700 hover:text-teal-900"
                      >
                        打开表单入口 <ArrowUpRight className="h-3.5 w-3.5" />
                      </a>
                    ) : (
                      <div className="rounded-2xl border border-amber-200 bg-amber-50/80 p-3 text-amber-900">
                        表单视图已创建，但还没有拿到可直接分享的链接。通常需要在飞书 UI 内确认共享状态。
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-[24px] border border-slate-200 bg-white/90 p-5">
                  <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Execution Blueprint</div>
                  <div className="mt-2 text-xl font-semibold text-slate-950">原生执行层就绪度</div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    {nativeWorkflowBlueprints.slice(0, 3).map((item) => (
                      <div key={textValue(item.name)} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                        <div className="text-sm font-semibold text-slate-950">{textValue(item.name)}</div>
                        <div className="mt-2 text-sm leading-6 text-slate-600">
                          {textValue(item.entry_condition) || textValue(item.route_field) || '等待配置'}
                        </div>
                      </div>
                    ))}
                    {nativeWorkflowBlueprints.length === 0 && <EmptyState text="当前没有可展示的原生工作流蓝图。" />}
                  </div>
                </div>
              </div>

              <div className="mt-6 grid gap-4 xl:grid-cols-3">
                {[
                  { title: '自动化模板', items: nativeAutomationTemplates, style: 'border-emerald-200 bg-emerald-50 text-emerald-700', valueKey: 'condition' },
                  { title: '仪表盘蓝图', items: nativeDashboardBlueprints, style: 'border-violet-200 bg-violet-50 text-violet-700', valueKey: 'focus_metrics' },
                  { title: '角色蓝图', items: nativeRoleBlueprints, style: 'border-amber-200 bg-amber-50 text-amber-700', valueKey: 'focus_views' },
                ].map((lane) => (
                  <div key={lane.title} className="rounded-[24px] border border-slate-200 bg-white/90 p-4 shadow-sm">
                    <div className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${lane.style}`}>{lane.title}</div>
                    <div className="mt-4 space-y-3">
                      {lane.items.slice(0, 4).map((item) => (
                        <div key={textValue(item.name)} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                          <div className="text-sm font-semibold text-slate-950">{textValue(item.name)}</div>
                          <div className="mt-2 text-sm leading-6 text-slate-600">
                            {Array.isArray(item[lane.valueKey])
                              ? (item[lane.valueKey] as unknown[]).slice(0, 3).map((value) => String(value || '')).filter(Boolean).join(' / ')
                              : textValue(item[lane.valueKey]) || '等待配置'}
                          </div>
                        </div>
                      ))}
                      {lane.items.length === 0 && <EmptyState text={`当前没有可展示的${lane.title}。`} />}
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-[30px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Role Workspace</p>
                  <h2 className="mt-2 font-serif text-3xl font-semibold text-slate-950">角色化交付工作台</h2>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                    按拍板人、执行人、复核人、复盘负责人拆开待办队列，让多维表格交付闭环真正落到角色工作面，而不是只停留在任务总览。
                  </p>
                </div>
                <div className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
                  角色待办 {roleWorkspace.approval.length + roleWorkspace.execution.length + roleWorkspace.review.length + roleWorkspace.retrospective.length} 条
                </div>
              </div>

              <div className="mt-6 grid gap-4 xl:grid-cols-2 2xl:grid-cols-4">
                {[
                  {
                    key: 'approval',
                    title: '拍板人队列',
                    note: '等待管理层确认是否拍板',
                    items: roleWorkspace.approval,
                    accent: 'border-rose-200 bg-rose-50 text-rose-700',
                    button: '回写拍板',
                    action: 'approve' as const,
                    empty: '当前没有待拍板任务。',
                  },
                  {
                    key: 'execution',
                    title: '执行人队列',
                    note: '待推进并回写执行完成',
                    items: roleWorkspace.execution,
                    accent: 'border-sky-200 bg-sky-50 text-sky-700',
                    button: '回写执行完成',
                    action: 'execute' as const,
                    empty: '当前没有待执行落地任务。',
                  },
                  {
                    key: 'review',
                    title: '复核人队列',
                    note: '待补数、待重跑或待安排复核',
                    items: roleWorkspace.review,
                    accent: 'border-amber-200 bg-amber-50 text-amber-700',
                    button: '',
                    action: null,
                    empty: '当前没有待复核任务。',
                  },
                  {
                    key: 'retrospective',
                    title: '复盘队列',
                    note: '交付已完成，待正式进入复盘',
                    items: roleWorkspace.retrospective,
                    accent: 'border-violet-200 bg-violet-50 text-violet-700',
                    button: '标记进入复盘',
                    action: 'retrospective' as const,
                    empty: '当前没有待进入复盘的任务。',
                  },
                ].map((lane) => (
                  <div key={lane.key} className="rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.86),rgba(255,255,255,0.98))] p-4 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${lane.accent}`}>
                          {lane.title}
                        </div>
                        <div className="mt-3 text-sm leading-6 text-slate-600">{lane.note}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-semibold text-slate-950">{lane.items.length}</div>
                        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Tasks</div>
                      </div>
                    </div>

                    {lane.items.length === 0 ? (
                      <div className="mt-4">
                        <EmptyState text={lane.empty} />
                      </div>
                    ) : (
                      <div className="mt-4 space-y-3">
                        {lane.items.slice(0, 4).map((task) => (
                          <div key={task.record_id} className="rounded-[20px] border border-slate-200 bg-white/92 p-4">
                            <button
                              type="button"
                              onClick={() => setSelectedTaskId(task.record_id)}
                              className="w-full text-left"
                            >
                              <div className="text-sm font-semibold leading-6 text-slate-950">{taskTitle(task)}</div>
                              <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                                {textValue(task.fields?.输出目的) && (
                                  <span className={`rounded-full border px-2.5 py-1 ${PURPOSE_STYLE[textValue(task.fields?.输出目的)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                    {textValue(task.fields?.输出目的)}
                                  </span>
                                )}
                                {textValue(task.fields?.工作流路由) && (
                                  <span className={`rounded-full border px-2.5 py-1 ${ROUTE_STYLE[textValue(task.fields?.工作流路由)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                    {textValue(task.fields?.工作流路由)}
                                  </span>
                                )}
                              </div>
                              <div className="mt-3 grid gap-2 text-xs text-slate-500">
                                <div>
                                  负责人：
                                  {lane.key === 'approval'
                                    ? textValue(task.fields?.拍板人) || textValue(task.fields?.汇报对象) || '待指定'
                                    : lane.key === 'execution'
                                      ? textValue(task.fields?.执行负责人) || '待指定'
                                      : lane.key === 'review'
                                        ? textValue(task.fields?.复核负责人) || '待指定'
                                        : textValue(task.fields?.执行负责人) || textValue(task.fields?.汇报对象) || '待指定'}
                                </div>
                                <div>
                                  时间：
                                  {lane.key === 'approval'
                                    ? formatDateValue(task.fields?.拍板时间)
                                    : lane.key === 'execution'
                                      ? formatDateValue(task.fields?.执行截止时间)
                                      : lane.key === 'review'
                                        ? formatDateValue(task.fields?.建议复核时间)
                                        : formatDateValue(task.fields?.执行完成时间)}
                                </div>
                              </div>
                            </button>
                            {lane.action && (
                              <div className="mt-4">
                                <Button
                                  variant="outline"
                                  className="w-full rounded-full"
                                  onClick={() =>
                                    handleManagementConfirm(
                                      lane.action,
                                      lane.action === 'approve'
                                        ? '已确认拍板'
                                        : lane.action === 'execute'
                                          ? '已确认执行落地'
                                          : '已标记进入复盘',
                                      task,
                                    )
                                  }
                                >
                                  {lane.button}
                                </Button>
                              </div>
                            )}
                          </div>
                        ))}
                        {lane.items.length > 4 && (
                          <div className="px-2 text-xs text-slate-500">还有 {lane.items.length - 4} 条未展开显示。</div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-[30px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Exception Radar</p>
                  <h2 className="mt-2 font-serif text-3xl font-semibold text-slate-950">交付异常雷达</h2>
                  <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                    这里不看正常流转，只看真正可能拖慢产出的异常节点：拍板滞留、执行超期、复核超时、复盘迟迟不启动。
                  </p>
                </div>
                <div className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
                  异常 {exceptionWorkspace.approvalStale.length + exceptionWorkspace.executionOverdue.length + exceptionWorkspace.reviewOverdue.length + exceptionWorkspace.retrospectiveStale.length} 条
                </div>
              </div>

              <div className="mt-6 grid gap-4 xl:grid-cols-2 2xl:grid-cols-4">
                {[
                  {
                    key: 'approval-stale',
                    title: '拍板滞留',
                    note: '等待拍板超过 24 小时',
                    items: exceptionWorkspace.approvalStale,
                    accent: 'border-rose-200 bg-rose-50 text-rose-700',
                    empty: '当前没有超 24 小时未拍板任务。',
                  },
                  {
                    key: 'execution-overdue',
                    title: '执行超期',
                    note: '已到执行截止时间仍未回写完成',
                    items: exceptionWorkspace.executionOverdue,
                    accent: 'border-orange-200 bg-orange-50 text-orange-700',
                    empty: '当前没有执行超期任务。',
                  },
                  {
                    key: 'review-overdue',
                    title: '复核超时',
                    note: '建议复核时间已到但仍未关闭复核链路',
                    items: exceptionWorkspace.reviewOverdue,
                    accent: 'border-amber-200 bg-amber-50 text-amber-700',
                    empty: '当前没有复核超时任务。',
                  },
                  {
                    key: 'retrospective-stale',
                    title: '复盘滞后',
                    note: '执行完成超过 48 小时仍未进入复盘',
                    items: exceptionWorkspace.retrospectiveStale,
                    accent: 'border-violet-200 bg-violet-50 text-violet-700',
                    empty: '当前没有复盘滞后任务。',
                  },
                ].map((lane) => (
                  <div key={lane.key} className="rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.86),rgba(255,255,255,0.98))] p-4 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${lane.accent}`}>
                          {lane.title}
                        </div>
                        <div className="mt-3 text-sm leading-6 text-slate-600">{lane.note}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-2xl font-semibold text-slate-950">{lane.items.length}</div>
                        <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Cases</div>
                      </div>
                    </div>

                    {lane.items.length === 0 ? (
                      <div className="mt-4">
                        <EmptyState text={lane.empty} />
                      </div>
                    ) : (
                      <div className="mt-4 space-y-3">
                        {lane.items.slice(0, 4).map((task) => (
                          <button
                            key={task.record_id}
                            type="button"
                            onClick={() => setSelectedTaskId(task.record_id)}
                            className="w-full rounded-[20px] border border-slate-200 bg-white/92 p-4 text-left transition hover:border-slate-300"
                          >
                            <div className="text-sm font-semibold leading-6 text-slate-950">{taskTitle(task)}</div>
                            <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                              {textValue(task.fields?.工作流路由) && (
                                <span className={`rounded-full border px-2.5 py-1 ${ROUTE_STYLE[textValue(task.fields?.工作流路由)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                  {textValue(task.fields?.工作流路由)}
                                </span>
                              )}
                              {textValue(task.fields?.输出目的) && (
                                <span className={`rounded-full border px-2.5 py-1 ${PURPOSE_STYLE[textValue(task.fields?.输出目的)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                  {textValue(task.fields?.输出目的)}
                                </span>
                              )}
                            </div>
                            <div className="mt-3 text-xs leading-6 text-slate-500">
                              {lane.key === 'approval-stale' && `滞留时长：${hoursSince(task.fields?.完成日期 || task.fields?.最近更新)} 小时`}
                              {lane.key === 'execution-overdue' && `执行截止：${formatDateValue(task.fields?.执行截止时间)}`}
                              {lane.key === 'review-overdue' && `建议复核：${formatDateValue(task.fields?.建议复核时间)}`}
                              {lane.key === 'retrospective-stale' && `执行完成后已过：${hoursSince(task.fields?.执行完成时间)} 小时`}
                            </div>
                          </button>
                        ))}
                        {lane.items.length > 4 && (
                          <div className="px-2 text-xs text-slate-500">还有 {lane.items.length - 4} 条未展开显示。</div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>

            <section className="grid gap-6 xl:grid-cols-[1.18fr_0.82fr]">
              <div className="rounded-[30px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                <div className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Executive Dossier</p>
                      <h2 className="mt-2 font-serif text-3xl font-semibold text-slate-950">单任务汇报审阅台</h2>
                      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
                        这里展示的是管理层真正需要看的材料：任务背景、CEO 摘要、评审动作、证据骨架和再流转队列。
                      </p>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm text-slate-600">
                      当前选中任务：{selectedTitle || '暂无'}
                    </div>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {taskSwitcher.map((task) => {
                      const status = textValue(task.fields?.状态) || '待分析';
                      const purpose = textValue(task.fields?.输出目的);
                      const reviewAction = taskReviewAction(task, latestReviewByTitle.get(taskTitle(task)) || null);
                      const workflowRoute = taskWorkflowRoute(task);
                      const readinessScore = taskReadinessScore(task, latestReviewByTitle.get(taskTitle(task)) || null);
                      const isSelected = task.record_id === selectedTask?.record_id;
                      return (
                        <button
                          key={task.record_id}
                          type="button"
                          onClick={() => setSelectedTaskId(task.record_id)}
                          className={`rounded-[22px] border p-4 text-left transition ${isSelected ? 'border-teal-300 bg-teal-50/70 shadow-sm' : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/70'}`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${STATUS_STYLE[status]?.chip || 'border border-slate-200 bg-slate-100 text-slate-600'}`}>
                              {status}
                            </span>
                            <span className="text-xs text-slate-400">{textValue(task.fields?.优先级) || '未分级'}</span>
                          </div>
                          <div className="mt-3 line-clamp-2 text-sm font-semibold leading-6 text-slate-950">
                            {taskTitle(task)}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500">
                            {purpose && (
                              <span className={`rounded-full border px-2.5 py-1 ${PURPOSE_STYLE[purpose] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                {purpose}
                              </span>
                            )}
                            {reviewAction && (
                              <span className={`rounded-full border px-2.5 py-1 ${RECOMMENDATION_STYLE[reviewAction] || 'border-slate-200 bg-white text-slate-600'}`}>
                                {reviewAction}
                              </span>
                            )}
                            {workflowRoute && (
                              <span className={`rounded-full border px-2.5 py-1 ${ROUTE_STYLE[workflowRoute] || 'border-slate-200 bg-white text-slate-600'}`}>
                                {workflowRoute}
                              </span>
                            )}
                            {textValue(task.fields?.目标对象) && (
                              <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                                给 {textValue(task.fields?.目标对象)}
                              </span>
                            )}
                          </div>
                          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                            <span>证据 {numberValue(task.fields?.证据条数)}</span>
                            <span>就绪度 {readinessScore}/5</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  {selectedTask ? (
                    <div className="grid gap-6 xl:grid-cols-[1.12fr_0.88fr]">
                      <div className="space-y-6">
                        <div className="overflow-hidden rounded-[28px] border border-slate-200 bg-[linear-gradient(135deg,rgba(15,118,110,0.08),rgba(255,255,255,0.98)_38%,rgba(14,165,233,0.08))] p-6">
                          <div className="flex flex-wrap items-start justify-between gap-4">
                            <div className="max-w-3xl">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className={`rounded-full px-3 py-1 text-xs font-medium ${STATUS_STYLE[textValue(selectedTask.fields?.状态)]?.chip || 'border border-slate-200 bg-slate-100 text-slate-600'}`}>
                                  {textValue(selectedTask.fields?.状态) || '待分析'}
                                </span>
                                {textValue(selectedTask.fields?.输出目的) && (
                                  <span className={`rounded-full border px-3 py-1 text-xs font-medium ${PURPOSE_STYLE[textValue(selectedTask.fields?.输出目的)] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                    {textValue(selectedTask.fields?.输出目的)}
                                  </span>
                                )}
                                {taskReviewAction(selectedTask, selectedReview) && (
                                  <span className={`rounded-full border px-3 py-1 text-xs font-medium ${RECOMMENDATION_STYLE[taskReviewAction(selectedTask, selectedReview)] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                    {taskReviewAction(selectedTask, selectedReview)}
                                  </span>
                                )}
                                {taskWorkflowRoute(selectedTask) && (
                                  <span className={`rounded-full border px-3 py-1 text-xs font-medium ${ROUTE_STYLE[taskWorkflowRoute(selectedTask)] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                    {taskWorkflowRoute(selectedTask)}
                                  </span>
                                )}
                              </div>
                              <h3 className="mt-4 font-serif text-3xl font-semibold leading-tight text-slate-950">
                                {selectedTitle}
                              </h3>
                              <p className="mt-4 max-w-3xl text-sm leading-7 text-slate-700">{selectedSummaryText}</p>
                            </div>

                            <div className="w-full max-w-xs rounded-[24px] border border-white/70 bg-white/90 p-4 shadow-sm">
                              <div className="text-xs uppercase tracking-[0.22em] text-slate-500">Readiness</div>
                              <div className="mt-3 space-y-3">
                                <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-3">
                                  <div className="text-xs text-slate-500">证据充分度</div>
                                  <div className="mt-2 text-lg font-semibold text-slate-950">
                                    {scoreStars(selectedReport?.fields?.证据充分度 || selectedTask?.fields?.汇报就绪度 || 0)}
                                  </div>
                                </div>
                                <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-3">
                                  <div className="text-xs text-slate-500">决策紧急度</div>
                                  <div className="mt-2 text-lg font-semibold text-slate-950">
                                    {scoreStars(selectedReport?.fields?.决策紧急度 || 0)}
                                  </div>
                                </div>
                                <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-3">
                                  <div className="text-xs text-slate-500">主表汇报就绪度</div>
                                  <div className="mt-2 text-lg font-semibold text-slate-950">
                                    {scoreStars(taskReadinessScore(selectedTask, selectedReview))}
                                  </div>
                                </div>
                                <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-3">
                                  <div className="text-xs text-slate-500">引用数据集</div>
                                  <div className="mt-2 text-sm font-medium text-slate-950">
                                    {textValue(selectedTask.fields?.引用数据集) || '未绑定数据资产'}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </div>

                          <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                              {[
                                { label: '目标对象', value: textValue(selectedTask.fields?.目标对象) || '未指定' },
                                { label: '业务阶段', value: textValue(selectedTask.fields?.业务阶段) || '未指定' },
                                { label: '当前阶段', value: selectedLive?.stage || textValue(selectedTask.fields?.当前阶段) || '等待调度' },
                                { label: '成功标准', value: textValue(selectedTask.fields?.成功标准) || '未填写' },
                                { label: '证据条数', value: `${numberValue(selectedTask.fields?.证据条数)} 条` },
                                { label: '高置信证据', value: `${numberValue(selectedTask.fields?.高置信证据数)} 条` },
                                { label: '硬证据', value: `${numberValue(selectedTask.fields?.硬证据数)} 条` },
                                { label: '待验证证据', value: `${numberValue(selectedTask.fields?.待验证证据数)} 条` },
                                { label: '进入 CEO 汇总', value: `${numberValue(selectedTask.fields?.进入CEO汇总证据数)} 条` },
                                { label: '需补数条数', value: `${numberValue(selectedTask.fields?.需补数条数)} 条` },
                              ].map((item) => (
                                <div key={item.label} className="rounded-2xl border border-white/80 bg-white/88 p-4 shadow-sm">
                                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                                <div className="mt-2 text-sm font-medium leading-6 text-slate-950">{item.value}</div>
                              </div>
                            ))}
                          </div>

                          <div className="mt-6 rounded-2xl border border-slate-200 bg-white/85 p-4">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-medium text-slate-950">任务推进进度</div>
                              <div className="text-xs text-slate-500">
                                {selectedLive ? formatRelativeTime(selectedLive.updatedAt) : '等待更新'}
                              </div>
                            </div>
                            <div className="mt-3">
                              <Progress value={selectedProgress} className="h-2.5" />
                              <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                                <span>{selectedLive?.stage || textValue(selectedTask.fields?.当前阶段) || '等待调度'}</span>
                                <span>{selectedProgress.toFixed(0)}%</span>
                              </div>
                            </div>
                          </div>

                          <div className="mt-6 grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
                            <div className="rounded-[24px] border border-slate-200 bg-white/90 p-5 shadow-sm">
                              <div className="text-xs uppercase tracking-[0.2em] text-slate-500">One-Liner</div>
                              <div className="mt-3 font-serif text-2xl font-semibold leading-tight text-slate-950">
                                {selectedOneLiner}
                              </div>
                              <div className="mt-4 text-sm leading-7 text-slate-600">
                                {textValue(selectedReport?.fields?.首要动作) || splitListText(selectedReport?.fields?.立即执行事项, 1)[0] || '待补充首要动作'}
                              </div>
                            </div>

                            <div className="rounded-[24px] border border-slate-200 bg-[linear-gradient(135deg,rgba(255,255,255,0.96),rgba(240,253,250,0.92))] p-5 shadow-sm">
                              <div className="flex items-center justify-between gap-3">
                                <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Executive One-Pager</div>
                                <div className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
                                  汇报版
                                </div>
                              </div>
                              <div className="mt-4 whitespace-pre-line text-sm leading-7 text-slate-700">
                                {selectedExecBrief}
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Decision Grid</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">CEO 决策拆解</h3>
                            </div>
                            <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                              {selectedReport ? '来自综合报告' : '等待 CEO 汇总'}
                            </div>
                          </div>
                          <div className="mt-5 grid gap-4 md:grid-cols-2">
                            {selectedDecisionColumns.map((column) => (
                              <div key={column.title} className="rounded-[22px] border border-slate-200 bg-slate-50/70 p-4">
                                <div className={`text-sm font-semibold ${column.tone}`}>{column.title}</div>
                                {column.items.length === 0 ? (
                                  <div className="mt-3 text-sm text-slate-500">当前没有该类事项。</div>
                                ) : (
                                  <div className="mt-3 space-y-2">
                                    {column.items.map((item) => (
                                      <div key={item} className="rounded-xl border border-white/80 bg-white/90 px-3 py-2 text-sm leading-6 text-slate-700">
                                        {item}
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>

                        <div className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="grid gap-4 lg:grid-cols-[0.82fr_1.18fr]">
                            <div className="rounded-[22px] border border-slate-200 bg-[linear-gradient(135deg,rgba(248,250,252,0.92),rgba(255,255,255,0.98))] p-4">
                              <div className="text-xs uppercase tracking-[0.2em] text-slate-500">Evidence Structure</div>
                              <div className="mt-4 space-y-3">
                                {[
                                  { label: '硬证据', value: selectedEvidenceOverview.hard, style: EVIDENCE_GRADE_STYLE['硬证据'] },
                                  { label: '推断', value: selectedEvidenceOverview.inferred, style: EVIDENCE_GRADE_STYLE['推断'] },
                                  { label: '待验证', value: selectedEvidenceOverview.pending, style: EVIDENCE_GRADE_STYLE['待验证'] },
                                ].map((item) => (
                                  <div key={item.label} className={`rounded-2xl border px-4 py-3 ${item.style}`}>
                                    <div className="flex items-center justify-between gap-3">
                                      <span className="text-sm font-medium">{item.label}</span>
                                      <span className="text-2xl font-semibold">{item.value}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>

                            <div>
                              <div className="flex items-center justify-between gap-3">
                                <div>
                                  <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Evidence Chain</p>
                                  <h3 className="mt-2 text-2xl font-semibold text-slate-950">证据链精选</h3>
                                </div>
                                <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                                  共 {selectedEvidence.length} 条
                                </div>
                              </div>
                              <p className="mt-3 text-sm leading-6 text-slate-600">
                                硬证据用于支撑汇报主结论，推断用于解释方向，待验证项会直接影响是否需要补数复核。
                              </p>
                            </div>
                          </div>
                          {selectedEvidence.length === 0 ? (
                            <div className="mt-5">
                              <EmptyState text="该任务当前还没有落表的结构化证据。" />
                            </div>
                          ) : (
                            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                              {selectedEvidence.slice(0, 6).map((record) => {
                                const usage = textValue(record.fields?.证据用途);
                                const confidence = textValue(record.fields?.证据置信度);
                                return (
                                  <div key={record.record_id} className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                                    <div className="flex flex-wrap gap-2">
                                      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600">
                                        {textValue(record.fields?.岗位角色) || '未标注角色'}
                                      </span>
                                      {usage && (
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${EVIDENCE_USAGE_STYLE[usage] || 'border-slate-200 bg-white text-slate-600'}`}>
                                          {usage}
                                        </span>
                                      )}
                                      {confidence && (
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${CONFIDENCE_STYLE[confidence] || 'border-slate-200 bg-white text-slate-600'}`}>
                                          {confidence}
                                        </span>
                                      )}
                                      {textValue(record.fields?.证据等级) && (
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${EVIDENCE_GRADE_STYLE[textValue(record.fields?.证据等级)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                          {textValue(record.fields?.证据等级)}
                                        </span>
                                      )}
                                    </div>
                                    <div className="mt-3 text-sm font-semibold leading-6 text-slate-950">
                                      {textValue(record.fields?.结论摘要) || '未生成结论摘要'}
                                    </div>
                                    <p className="mt-3 line-clamp-4 text-sm leading-6 text-slate-600">
                                      {textValue(record.fields?.证据内容) || textValue(record.fields?.引用来源) || '暂无展开内容'}
                                    </p>
                                    <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                                      <span>{textValue(record.fields?.证据类型) || 'judgment'}</span>
                                      <span>{booleanValue(record.fields?.进入CEO汇总) ? '已进 CEO 汇总' : '岗位内证据'}</span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="space-y-6">
                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Review Board</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">产出评审</h3>
                            </div>
                            <div className={`rounded-full border px-3 py-1 text-xs font-medium ${RECOMMENDATION_STYLE[taskReviewAction(selectedTask, selectedReview)] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                              {taskReviewAction(selectedTask, selectedReview) || '待评审'}
                            </div>
                          </div>

                          <div className="mt-5 rounded-[22px] border border-slate-200 bg-[linear-gradient(135deg,rgba(15,118,110,0.06),rgba(255,255,255,0.92))] p-4">
                            <div className="text-sm leading-7 text-slate-700">
                              {textValue(selectedReview?.fields?.评审结论) || textValue(selectedReview?.fields?.评审摘要) || '任务尚未形成评审结论。'}
                            </div>
                          </div>

                          <div className="mt-5 space-y-3">
                            {selectedReviewScores.map((item) => (
                              <div key={item.label} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                                <div className="flex items-center justify-between gap-3">
                                  <span className="text-sm font-medium text-slate-950">{item.label}</span>
                                  <span className="text-sm font-semibold text-slate-700">{scoreStars(item.value)}</span>
                                </div>
                                <div className="mt-3">
                                  <Progress value={item.value * 20} className="h-2" />
                                </div>
                              </div>
                            ))}
                          </div>
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Recheck Queue</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">再流转任务</h3>
                            </div>
                            <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                              {selectedFollowups.length} 条
                            </div>
                          </div>
                          {selectedFollowups.length === 0 ? (
                            <div className="mt-5">
                              <EmptyState text="当前任务还没有派生出的复核或跟进任务。" />
                            </div>
                          ) : (
                            <div className="mt-5 space-y-3">
                              {selectedFollowups.map((task) => (
                                <button
                                  key={task.record_id}
                                  type="button"
                                  onClick={() => setSelectedTaskId(task.record_id)}
                                  className="w-full rounded-[22px] border border-slate-200 bg-slate-50/80 p-4 text-left transition hover:border-slate-300 hover:bg-slate-50"
                                >
                                  <div className="flex items-center justify-between gap-3">
                                    <div className="text-sm font-semibold leading-6 text-slate-950">{taskTitle(task)}</div>
                                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${STATUS_STYLE[textValue(task.fields?.状态)]?.chip || 'border border-slate-200 bg-slate-100 text-slate-600'}`}>
                                      {textValue(task.fields?.状态) || '待分析'}
                                    </span>
                                  </div>
                                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
                                    {textValue(task.fields?.输出目的) && (
                                      <span className={`rounded-full border px-2.5 py-1 ${PURPOSE_STYLE[textValue(task.fields?.输出目的)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                        {textValue(task.fields?.输出目的)}
                                      </span>
                                    )}
                                    {textValue(task.fields?.依赖任务编号) && (
                                      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                                        依赖 {textValue(task.fields?.依赖任务编号)}
                                      </span>
                                    )}
                                    {taskResponsibilityRole(task) && (
                                      <span className={`rounded-full border px-2.5 py-1 ${RESPONSIBILITY_STYLE[taskResponsibilityRole(task)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                        {taskResponsibilityRole(task)}
                                      </span>
                                    )}
                                    {taskExceptionStatus(task) && taskExceptionStatus(task) !== '正常' && (
                                      <span className={`rounded-full border px-2.5 py-1 ${EXCEPTION_STATUS_STYLE[taskExceptionStatus(task)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                        {taskExceptionType(task) || taskExceptionStatus(task)}
                                      </span>
                                    )}
                                  </div>
                                </button>
                              ))}
                            </div>
                          )}
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Native Automation</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">多维表格原生工作流交接包</h3>
                            </div>
                            <div className={`rounded-full border px-3 py-1 text-xs font-medium ${ROUTE_STYLE[taskWorkflowRoute(selectedTask)] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                              {taskWorkflowRoute(selectedTask) || '待生成路由'}
                            </div>
                          </div>

                          <div className="mt-5 grid gap-4 md:grid-cols-3">
                            {[
                              { label: '待发送汇报', value: booleanValue(selectedTask.fields?.待发送汇报) ? '是' : '否' },
                              { label: '待创建执行任务', value: booleanValue(selectedTask.fields?.待创建执行任务) ? '是' : '否' },
                              { label: '待安排复核', value: booleanValue(selectedTask.fields?.待安排复核) ? '是' : '否' },
                            ].map((item) => (
                              <div key={item.label} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                                <div className="mt-2 text-lg font-semibold text-slate-950">{item.value}</div>
                              </div>
                            ))}
                          </div>

                          <div className="mt-5 grid gap-4 xl:grid-cols-4">
                            {[
                              {
                                label: '当前责任角色',
                                value: taskResponsibilityRole(selectedTask) || '系统调度',
                                style: RESPONSIBILITY_STYLE[taskResponsibilityRole(selectedTask)] || 'border-slate-200 bg-slate-50 text-slate-600',
                              },
                              {
                                label: '当前责任人',
                                value: textValue(selectedTask.fields?.当前责任人) || '未指定',
                                style: 'border-slate-200 bg-slate-50 text-slate-700',
                              },
                              {
                                label: '当前原生动作',
                                value: taskNativeAction(selectedTask) || '待生成',
                                style: NATIVE_ACTION_STYLE[taskNativeAction(selectedTask)] || 'border-slate-200 bg-slate-50 text-slate-600',
                              },
                              {
                                label: '异常状态',
                                value: taskExceptionType(selectedTask) && taskExceptionType(selectedTask) !== '无'
                                  ? `${taskExceptionStatus(selectedTask) || '正常'} · ${taskExceptionType(selectedTask)}`
                                  : taskExceptionStatus(selectedTask) || '正常',
                                style: EXCEPTION_STATUS_STYLE[taskExceptionStatus(selectedTask)] || 'border-emerald-200 bg-emerald-50 text-emerald-700',
                              },
                            ].map((item) => (
                              <div key={item.label} className="rounded-2xl border border-slate-200 bg-white/90 p-4">
                                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                                <div className={`mt-3 inline-flex rounded-full border px-3 py-1 text-sm font-medium ${item.style}`}>{item.value}</div>
                              </div>
                            ))}
                          </div>

                          {textValue(selectedTask.fields?.异常说明) && (
                            <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-sm leading-7 text-amber-900">
                              {textValue(selectedTask.fields?.异常说明)}
                            </div>
                          )}

                          <div className="mt-5 grid gap-4 xl:grid-cols-2">
                            <div className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                              <div className="flex items-center justify-between gap-3">
                                <div className="text-sm font-semibold text-slate-950">工作流消息包</div>
                                <div className="text-xs text-slate-500">用于飞书消息/邮件动作</div>
                              </div>
                              <div className="mt-3 whitespace-pre-line text-sm leading-7 text-slate-700">
                                {textValue(selectedTask.fields?.工作流消息包) || '待生成'}
                              </div>
                            </div>

                            <div className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                              <div className="flex items-center justify-between gap-3">
                                <div className="text-sm font-semibold text-slate-950">工作流执行包</div>
                                <div className="text-xs text-slate-500">用于飞书任务/审批/复核动作</div>
                              </div>
                              <div className="mt-3 whitespace-pre-line text-sm leading-7 text-slate-700">
                                {textValue(selectedTask.fields?.工作流执行包) || '待生成'}
                              </div>
                              <div className="mt-4 text-xs text-slate-500">
                                建议复核时间：{formatDateValue(selectedTask.fields?.建议复核时间)}
                              </div>
                            </div>
                          </div>
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Management Loop</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">管理确认闭环</h3>
                            </div>
                            <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                              主表回写驱动
                            </div>
                          </div>

                          <div className="mt-5 grid gap-4 md:grid-cols-3">
                            {selectedManagementFlags.map((item) => (
                              <div key={item.label} className={`rounded-[22px] border p-4 ${item.tone}`}>
                                <div className="text-xs uppercase tracking-[0.18em] opacity-70">{item.label}</div>
                                <div className="mt-2 text-2xl font-semibold">{item.value}</div>
                                <div className="mt-3 text-xs leading-6 opacity-80">{item.note}</div>
                              </div>
                            ))}
                          </div>

                          <div className="mt-5 flex flex-wrap gap-3">
                            <Button
                              variant="outline"
                              className="rounded-full"
                              disabled={booleanValue(selectedTask.fields?.是否已拍板)}
                              onClick={() => handleManagementConfirm('approve', '已确认拍板')}
                            >
                              <ShieldAlert className="mr-2 h-4 w-4" /> 回写拍板
                            </Button>
                            <Button
                              variant="outline"
                              className="rounded-full"
                              disabled={booleanValue(selectedTask.fields?.是否已执行落地)}
                              onClick={() => handleManagementConfirm('execute', '已确认执行落地')}
                            >
                              <ArrowUpRight className="mr-2 h-4 w-4" /> 回写执行完成
                            </Button>
                            <Button
                              variant="outline"
                              className="rounded-full"
                              disabled={booleanValue(selectedTask.fields?.是否进入复盘)}
                              onClick={() => handleManagementConfirm('retrospective', '已标记进入复盘')}
                            >
                              <RefreshCw className="mr-2 h-4 w-4" /> 标记进入复盘
                            </Button>
                          </div>

                          <div className="mt-5 grid gap-4 xl:grid-cols-2">
                            <div className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                              <div className="text-sm font-semibold text-slate-950">确认责任人</div>
                              <div className="mt-3 grid gap-3 text-sm text-slate-700">
                                <div>汇报对象：{textValue(selectedTask.fields?.汇报对象) || '未指定'}</div>
                                <div>执行负责人：{textValue(selectedTask.fields?.执行负责人) || '未指定'}</div>
                                <div>复核负责人：{textValue(selectedTask.fields?.复核负责人) || '未指定'}</div>
                                <div>拍板人：{textValue(selectedTask.fields?.拍板人) || '待回写'}</div>
                              </div>
                            </div>

                            <div className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                              <div className="text-sm font-semibold text-slate-950">确认时间轴</div>
                              <div className="mt-3 grid gap-3 text-sm text-slate-700">
                                <div>拍板时间：{formatDateValue(selectedTask.fields?.拍板时间)}</div>
                                <div>执行截止时间：{formatDateValue(selectedTask.fields?.执行截止时间)}</div>
                                <div>执行完成时间：{formatDateValue(selectedTask.fields?.执行完成时间)}</div>
                                <div>建议复核时间：{formatDateValue(selectedTask.fields?.建议复核时间)}</div>
                              </div>
                            </div>
                          </div>
                        </section>

                        <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-white">
                          <div className="border-b border-slate-100 bg-[linear-gradient(135deg,rgba(8,145,178,0.12),rgba(14,165,233,0.06)_42%,rgba(255,255,255,1)_78%)] px-6 py-6">
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div>
                                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Delivery Timeline</p>
                                <h3 className="mt-2 text-2xl font-semibold text-slate-950">飞书原生交付动作</h3>
                                <p className="mt-2 text-sm leading-6 text-slate-600">
                                  这不是前端自说自话，而是从 `交付动作` 表回放本任务已经触发过的汇报、执行、复核与自动跟进。
                                </p>
                              </div>
                              <div className="flex flex-wrap gap-2 text-xs">
                                {[
                                  { label: '已完成', value: selectedActions.filter((item) => textValue(item.fields?.动作状态) === '已完成').length, cls: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
                                  { label: '已跳过', value: selectedActions.filter((item) => textValue(item.fields?.动作状态) === '已跳过').length, cls: 'border-slate-200 bg-slate-100 text-slate-600' },
                                  { label: '失败', value: selectedActions.filter((item) => textValue(item.fields?.动作状态) === '执行失败').length, cls: 'border-rose-200 bg-rose-50 text-rose-700' },
                                ].map((item) => (
                                  <div key={item.label} className={`rounded-full border px-3 py-1 font-medium ${item.cls}`}>
                                    {item.label} {item.value}
                                  </div>
                                ))}
                              </div>
                            </div>
                          </div>

                          <div className="px-6 py-6">
                            {selectedActions.length === 0 ? (
                              <EmptyState text="当前任务还没有沉淀交付动作。完成分析后，这里会展示消息发送、执行任务创建、复核任务创建和工作流记录。" />
                            ) : (
                              <div className="space-y-4">
                                {selectedActions.map((action, index) => {
                                  const actionType = textValue(action.fields?.动作类型);
                                  const actionStatus = textValue(action.fields?.动作状态);
                                  const actionRoute = textValue(action.fields?.工作流路由);
                                  const actionContent = textValue(action.fields?.动作内容);
                                  const actionResult = textValue(action.fields?.执行结果);
                                  return (
                                    <div key={action.record_id} className="relative rounded-[24px] border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.9),rgba(255,255,255,1))] p-5 shadow-sm">
                                      {index < selectedActions.length - 1 && (
                                        <div className="absolute left-9 top-[72px] h-[calc(100%+12px)] w-px bg-gradient-to-b from-slate-200 via-slate-200 to-transparent" />
                                      )}
                                      <div className="flex items-start gap-4">
                                        <div className="mt-1 flex h-8 w-8 items-center justify-center rounded-full bg-slate-950 text-xs font-semibold text-white">
                                          {index + 1}
                                        </div>
                                        <div className="min-w-0 flex-1">
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ACTION_TYPE_STYLE[actionType] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                              {actionType || '未标注动作'}
                                            </span>
                                            <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ACTION_STATUS_STYLE[actionStatus] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                              {actionStatus || '未知状态'}
                                            </span>
                                            {actionRoute && (
                                              <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ROUTE_STYLE[actionRoute] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                                {actionRoute}
                                              </span>
                                            )}
                                            <span className="text-xs text-slate-500">
                                              {formatDateValue(action.fields?.生成时间)}
                                            </span>
                                          </div>
                                          <div className="mt-3 text-base font-semibold text-slate-950">
                                            {textValue(action.fields?.动作标题) || '未命名动作'}
                                          </div>
                                          {actionContent && (
                                            <div className="mt-3 whitespace-pre-line rounded-2xl border border-slate-200 bg-white/90 p-4 text-sm leading-7 text-slate-700">
                                              {actionContent}
                                            </div>
                                          )}
                                          {actionResult && (
                                            <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50/90 p-4 text-sm leading-7 text-slate-600">
                                              {actionResult}
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Review History</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">复核历史与结论变化</h3>
                            </div>
                            <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                              {selectedReviewHistory.length} 条
                            </div>
                          </div>
                          {selectedReviewHistory.length === 0 ? (
                            <div className="mt-5">
                              <EmptyState text="当前任务还没有复核历史沉淀。进入补数复核或建议重跑后，这里会记录第几轮复核以及结论变化。" />
                            </div>
                          ) : (
                            <div className="mt-5 grid gap-4 xl:grid-cols-2">
                              {selectedReviewHistory.map((record) => {
                                const action = textValue(record.fields?.推荐动作);
                                return (
                                  <div key={record.record_id} className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${RECOMMENDATION_STYLE[action] || 'border-slate-200 bg-white text-slate-600'}`}>
                                        {action || '未标注动作'}
                                      </span>
                                      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600">
                                        第 {numberValue(record.fields?.复核轮次) || 0} 轮
                                      </span>
                                      <span className="text-xs text-slate-500">{formatDateValue(record.fields?.生成时间)}</span>
                                    </div>
                                    <div className="mt-3 text-sm font-semibold text-slate-950">
                                      {textValue(record.fields?.复核标题) || '未命名复核'}
                                    </div>
                                    <div className="mt-3 text-sm leading-7 text-slate-700">
                                      {textValue(record.fields?.新旧结论差异) || textValue(record.fields?.复核结论) || '暂无差异描述'}
                                    </div>
                                    {textValue(record.fields?.需补数事项) && (
                                      <div className="mt-3 rounded-2xl border border-slate-200 bg-white/90 p-4 text-sm leading-7 text-slate-600">
                                        {textValue(record.fields?.需补数事项)}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Delivery Archive</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">交付归档版本</h3>
                            </div>
                            <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                              {selectedArchiveRecords.length} 个版本
                            </div>
                          </div>
                          {selectedArchiveRecords.length === 0 ? (
                            <div className="mt-5">
                              <EmptyState text="当前任务还没有交付归档版本。任务完成后，这里会沉淀汇报版本、归档状态和交付摘要。" />
                            </div>
                          ) : (
                            <div className="mt-5 space-y-4">
                              {selectedArchiveRecords.map((record) => {
                                const archiveStatus = textValue(record.fields?.归档状态);
                                return (
                                  <div key={record.record_id} className="rounded-[22px] border border-slate-200 bg-[linear-gradient(135deg,rgba(248,250,252,0.92),rgba(255,255,255,1))] p-5">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700">
                                        {textValue(record.fields?.汇报版本号) || 'v?'}
                                      </span>
                                      <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ARCHIVE_STATUS_STYLE[archiveStatus] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                        {archiveStatus || '未归档'}
                                      </span>
                                      {textValue(record.fields?.工作流路由) && (
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ROUTE_STYLE[textValue(record.fields?.工作流路由)] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                          {textValue(record.fields?.工作流路由)}
                                        </span>
                                      )}
                                      <span className="text-xs text-slate-500">{formatDateValue(record.fields?.生成时间)}</span>
                                    </div>
                                    <div className="mt-3 text-base font-semibold text-slate-950">
                                      {textValue(record.fields?.一句话结论) || textValue(record.fields?.归档标题) || '未生成归档标题'}
                                    </div>
                                    <div className="mt-3 grid gap-3 md:grid-cols-3">
                                      {[
                                        { label: '汇报对象', value: textValue(record.fields?.汇报对象) || '未指定' },
                                        { label: '执行负责人', value: textValue(record.fields?.执行负责人) || '未指定' },
                                        { label: '复核负责人', value: textValue(record.fields?.复核负责人) || '未指定' },
                                      ].map((item) => (
                                        <div key={item.label} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-3">
                                          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                                          <div className="mt-2 text-sm font-medium text-slate-950">{item.value}</div>
                                        </div>
                                      ))}
                                    </div>
                                    <div className="mt-3 rounded-2xl border border-slate-200 bg-white/90 p-4 text-sm leading-7 text-slate-700">
                                      {textValue(record.fields?.管理摘要) || textValue(record.fields?.工作流消息包) || '暂无归档摘要'}
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <div className="flex items-center justify-between gap-3">
                            <div>
                              <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Automation Audit</p>
                              <h3 className="mt-2 text-2xl font-semibold text-slate-950">自动化节点审计</h3>
                            </div>
                            <div className="flex flex-wrap gap-2 text-xs">
                              {[
                                { label: '成功', value: selectedAutomationLogs.filter((item) => textValue(item.fields?.执行状态) === '已完成').length, cls: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
                                { label: '跳过', value: selectedAutomationLogs.filter((item) => textValue(item.fields?.执行状态) === '已跳过').length, cls: 'border-slate-200 bg-slate-100 text-slate-600' },
                                { label: '失败', value: selectedAutomationLogs.filter((item) => textValue(item.fields?.执行状态) === '执行失败').length, cls: 'border-rose-200 bg-rose-50 text-rose-700' },
                              ].map((item) => (
                                <div key={item.label} className={`rounded-full border px-3 py-1 font-medium ${item.cls}`}>
                                  {item.label} {item.value}
                                </div>
                              ))}
                            </div>
                          </div>
                          {selectedAutomationLogs.length === 0 ? (
                            <div className="mt-5">
                              <EmptyState text="当前任务还没有自动化节点审计。随着消息通知、执行任务、复核任务和归档节点运行，这里会记录每个节点的成功、跳过和失败。" />
                            </div>
                          ) : (
                            <div className="mt-5 space-y-3">
                              {selectedAutomationLogs.map((record) => {
                                const status = textValue(record.fields?.执行状态);
                                return (
                                  <div key={record.record_id} className="rounded-[22px] border border-slate-200 bg-slate-50/80 p-4">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ACTION_STATUS_STYLE[status] || 'border-slate-200 bg-white text-slate-600'}`}>
                                        {status || '未知状态'}
                                      </span>
                                      {textValue(record.fields?.工作流路由) && (
                                        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ROUTE_STYLE[textValue(record.fields?.工作流路由)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                          {textValue(record.fields?.工作流路由)}
                                        </span>
                                      )}
                                      <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-slate-600">
                                        {textValue(record.fields?.节点名称) || '未命名节点'}
                                      </span>
                                      <span className="text-xs text-slate-500">{formatDateValue(record.fields?.生成时间)}</span>
                                    </div>
                                    <div className="mt-3 text-sm font-semibold text-slate-950">
                                      {textValue(record.fields?.日志标题) || '未命名日志'}
                                    </div>
                                    <div className="mt-3 text-sm leading-7 text-slate-700">
                                      {textValue(record.fields?.日志摘要) || '暂无日志摘要'}
                                    </div>
                                    {textValue(record.fields?.详细结果) && (
                                      <div className="mt-3 rounded-2xl border border-slate-200 bg-white/90 p-4 text-sm leading-7 text-slate-600">
                                        {textValue(record.fields?.详细结果)}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </section>

                        <section className="rounded-[28px] border border-slate-200 bg-white p-6">
                          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Report Extract</p>
                          <h3 className="mt-2 text-2xl font-semibold text-slate-950">综合报告摘要</h3>
                          <div className="mt-5 space-y-3">
                            {[
                              { label: '一句话结论', value: textValue(selectedReport?.fields?.一句话结论) || selectedOneLiner },
                              { label: '核心结论', value: textValue(selectedReport?.fields?.核心结论) },
                              { label: '重要机会', value: textValue(selectedReport?.fields?.重要机会) },
                              { label: '重要风险', value: textValue(selectedReport?.fields?.重要风险) },
                              { label: 'CEO 决策事项', value: textValue(selectedReport?.fields?.CEO决策事项) },
                              { label: '汇报风险', value: textValue(selectedReport?.fields?.汇报风险) },
                            ].map((item) => (
                              <div key={item.label} className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">
                                <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{item.label}</div>
                                <div className="mt-2 text-sm leading-7 text-slate-700">{item.value || '暂无内容'}</div>
                              </div>
                            ))}
                          </div>
                        </section>
                      </div>
                    </div>
                  ) : (
                    <EmptyState text="当前没有可选任务。先写入一条分析任务或等待调度器生成数据。" />
                  )}
                </div>
              </div>

              <div className="space-y-6">
                <section className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Task Intake</p>
                      <h2 className="mt-2 text-2xl font-semibold text-slate-950">新增分析任务</h2>
                      <p className="mt-2 text-sm leading-6 text-slate-600">
                        这里写入的不只是标题和背景，还会把 `任务来源 / 业务归属 / 汇报对象级别 / 模板 / 负责人 / SLA`
                        一起沉淀到 `分析任务` 主表，直接成为后续多维表格原生自动化的触发契约。
                      </p>
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                      推荐：目标对象 + 成功标准 + 引用数据集
                    </div>
                  </div>

                  <div className="mt-5 grid gap-4">
                    <Input
                      placeholder="任务标题，如：2026Q2 增长下滑诊断与 CEO 决策建议"
                      value={newTaskTitle}
                      onChange={(e) => setNewTaskTitle(e.target.value)}
                      className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                    />
                    <Textarea
                      placeholder="背景说明：描述现象、问题、会议语境或管理层关切"
                      rows={4}
                      value={newTaskBackground}
                      onChange={(e) => setNewTaskBackground(e.target.value)}
                      className="rounded-2xl border-slate-200 bg-slate-50/80"
                    />
                    <div className="grid gap-4 md:grid-cols-3">
                      <Select value={newTaskSource} onValueChange={(value) => setNewTaskSource(value as (typeof TASK_SOURCE_OPTIONS)[number])}>
                        <SelectTrigger className="h-12 rounded-2xl border-slate-200 bg-slate-50/80">
                          <SelectValue placeholder="任务来源" />
                        </SelectTrigger>
                        <SelectContent>
                          {TASK_SOURCE_OPTIONS.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Select
                        value={newTaskBusinessOwner}
                        onValueChange={(value) => setNewTaskBusinessOwner(value as (typeof BUSINESS_OWNER_OPTIONS)[number])}
                      >
                        <SelectTrigger className="h-12 rounded-2xl border-slate-200 bg-slate-50/80">
                          <SelectValue placeholder="业务归属" />
                        </SelectTrigger>
                        <SelectContent>
                          {BUSINESS_OWNER_OPTIONS.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Select
                        value={newTaskAudienceLevel}
                        onValueChange={(value) => setNewTaskAudienceLevel(value as (typeof AUDIENCE_LEVEL_OPTIONS)[number])}
                      >
                        <SelectTrigger className="h-12 rounded-2xl border-slate-200 bg-slate-50/80">
                          <SelectValue placeholder="汇报对象级别" />
                        </SelectTrigger>
                        <SelectContent>
                          {AUDIENCE_LEVEL_OPTIONS.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Input
                        placeholder="目标对象，如：CEO / 产品负责人 / 经营会"
                        value={newTaskAudience}
                        onChange={(e) => setNewTaskAudience(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                      <Input
                        placeholder="引用数据集（可选），填写数据源库名称"
                        value={newTaskDatasetRef}
                        onChange={(e) => setNewTaskDatasetRef(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                    </div>
                    <div className="rounded-[22px] border border-slate-200 bg-[linear-gradient(135deg,rgba(139,92,246,0.08),rgba(255,255,255,0.96)_42%,rgba(14,165,233,0.08))] p-4 shadow-sm">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Template Assist</div>
                          <div className="mt-2 text-sm font-semibold text-slate-950">
                            模板驱动任务写入，默认负责人与 SLA 直接进多维表格
                          </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
                            推荐 {templateSuggestions.length} 个
                          </div>
                          <div className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600">
                            已启用 {templateOverview.total} 个
                          </div>
                        </div>
                      </div>
                      <div className="mt-4">
                        <Select
                          value={selectedTemplateId || 'auto'}
                          onValueChange={(value) => {
                            if (value === 'auto') {
                              setSelectedTemplateId('');
                              return;
                            }
                            const record = activeTemplates.find((item) => item.record_id === value);
                            if (record) applyTemplate(record);
                          }}
                        >
                          <SelectTrigger className="h-11 rounded-2xl border-white/70 bg-white/90">
                            <SelectValue placeholder="选择模板或使用自动匹配" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="auto">按输出目的自动匹配</SelectItem>
                            {activeTemplates.map((record) => (
                              <SelectItem key={record.record_id} value={record.record_id}>
                                {textValue(record.fields?.模板名称) || '未命名模板'}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      {templateSuggestions.length === 0 ? (
                        <div className="mt-3 text-sm text-slate-500">当前输出目的还没有可用模板。</div>
                      ) : (
                        <div className="mt-4 flex flex-wrap gap-2">
                          {templateSuggestions.slice(0, 5).map((record) => {
                            const isActive = selectedTemplateId === record.record_id;
                            return (
                              <button
                                key={record.record_id}
                                type="button"
                                onClick={() => applyTemplate(record)}
                                className={`rounded-full border px-3 py-2 text-xs font-medium transition ${isActive ? 'border-violet-300 bg-violet-50 text-violet-700' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'}`}
                              >
                                {textValue(record.fields?.模板名称) || '未命名模板'}
                              </button>
                            );
                          })}
                        </div>
                      )}
                      {selectedTemplate ? (
                        <div className="mt-4 rounded-[24px] border border-violet-200 bg-white/88 p-4">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="rounded-full border border-violet-200 bg-white px-3 py-1 text-[11px] font-medium text-violet-700">
                              {textValue(selectedTemplate.fields?.模板名称) || '未命名模板'}
                            </span>
                            {textValue(selectedTemplate.fields?.适用工作流路由) && (
                              <span className={`rounded-full border px-3 py-1 text-[11px] font-medium ${ROUTE_STYLE[textValue(selectedTemplate.fields?.适用工作流路由)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                {textValue(selectedTemplate.fields?.适用工作流路由)}
                              </span>
                            )}
                            {textValue(selectedTemplate.fields?.适用输出目的) && (
                              <span className={`rounded-full border px-3 py-1 text-[11px] font-medium ${PURPOSE_STYLE[textValue(selectedTemplate.fields?.适用输出目的)] || 'border-slate-200 bg-white text-slate-600'}`}>
                                {textValue(selectedTemplate.fields?.适用输出目的)}
                              </span>
                            )}
                          </div>
                          <p className="mt-3 text-sm leading-7 text-slate-700">
                            {textValue(selectedTemplate.fields?.模板说明) || '这份模板会成为当前任务的正式交付配置，写入任务表并在后续调度时优先使用。'}
                          </p>
                          <div className="mt-4 grid gap-3 md:grid-cols-2">
                            <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-700">
                              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">默认配置</div>
                              <div className="mt-3 space-y-2">
                                <div>汇报对象：{textValue(selectedTemplate.fields?.默认汇报对象) || '未指定'}</div>
                                <div>拍板负责人：{textValue(selectedTemplate.fields?.默认拍板负责人) || '未指定'}</div>
                                <div>执行负责人：{textValue(selectedTemplate.fields?.默认执行负责人) || '未指定'}</div>
                                <div>复核负责人：{textValue(selectedTemplate.fields?.默认复核负责人) || '未指定'}</div>
                                <div>复盘负责人：{textValue(selectedTemplate.fields?.默认复盘负责人) || '未指定'}</div>
                                <div>复核 SLA：{numberValue(selectedTemplate.fields?.默认复核SLA小时) > 0 ? `${numberValue(selectedTemplate.fields?.默认复核SLA小时)} 小时` : '未指定'}</div>
                              </div>
                            </div>
                            <div className="rounded-2xl border border-slate-200 bg-slate-50/80 p-4 text-sm text-slate-700">
                              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">生效方式</div>
                              <div className="mt-3 space-y-2">
                              <div>写入任务后自动记录 `套用模板`，在多维表格中可回溯。</div>
                                <div>后端会自动回填拍板、执行、复核、复盘负责人和复核 SLA。</div>
                                <div>进入交付阶段后，消息包与执行包优先按此模板渲染。</div>
                              </div>
                            </div>
                          </div>
                          <div className="mt-4 grid gap-3 md:grid-cols-2">
                            <div className="rounded-2xl border border-slate-200 bg-white/90 p-4">
                              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">汇报模板片段</div>
                              <div className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-700">
                                {textValue(selectedTemplate.fields?.汇报模板) || '未配置'}
                              </div>
                            </div>
                            <div className="rounded-2xl border border-slate-200 bg-white/90 p-4">
                              <div className="text-xs uppercase tracking-[0.18em] text-slate-500">执行模板片段</div>
                              <div className="mt-3 whitespace-pre-line text-sm leading-6 text-slate-700">
                                {textValue(selectedTemplate.fields?.执行模板) || '未配置'}
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white/70 px-4 py-3 text-sm text-slate-500">
                          未显式选择模板时，后端会按当前输出目的 `{newTaskPurpose}` 自动匹配启用模板并回填默认配置。
                        </div>
                      )}
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Select value={newTaskPurpose} onValueChange={(value) => setNewTaskPurpose(value as (typeof PURPOSE_OPTIONS)[number])}>
                        <SelectTrigger className="h-12 rounded-2xl border-slate-200 bg-slate-50/80">
                          <SelectValue placeholder="选择输出目的" />
                        </SelectTrigger>
                        <SelectContent>
                          {PURPOSE_OPTIONS.map((option) => (
                            <SelectItem key={option} value={option}>
                              {option}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Input
                        placeholder="成功标准，如：输出两个可直接拍板的方案"
                        value={newTaskSuccessCriteria}
                        onChange={(e) => setNewTaskSuccessCriteria(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Input
                        placeholder="汇报对象，如：CEO / 经营会 / 周例会"
                        value={newTaskReportAudience}
                        onChange={(e) => setNewTaskReportAudience(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                      <Input
                        placeholder="拍板负责人，如：CEO / 总经理 / 区域负责人"
                        value={newTaskApprovalOwner}
                        onChange={(e) => setNewTaskApprovalOwner(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Input
                        placeholder="执行负责人，如：增长负责人 / 区域运营"
                        value={newTaskExecutionOwner}
                        onChange={(e) => setNewTaskExecutionOwner(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Input
                        placeholder="复核负责人，如：数据分析负责人"
                        value={newTaskReviewOwner}
                        onChange={(e) => setNewTaskReviewOwner(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                      <Input
                        placeholder="复盘负责人，如：经营复盘负责人"
                        value={newTaskRetrospectiveOwner}
                        onChange={(e) => setNewTaskRetrospectiveOwner(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                    </div>
                    <div className="grid gap-4 md:grid-cols-2">
                      <Input
                        placeholder="复核 SLA 小时，如：24"
                        value={newTaskReviewSla}
                        onChange={(e) => setNewTaskReviewSla(e.target.value)}
                        className="h-12 rounded-2xl border-slate-200 bg-slate-50/80"
                      />
                    </div>
                    <Textarea
                      placeholder="约束条件：预算、人力、时间、组织边界、风险偏好等"
                      rows={3}
                      value={newTaskConstraints}
                      onChange={(e) => setNewTaskConstraints(e.target.value)}
                      className="rounded-2xl border-slate-200 bg-slate-50/80"
                    />
                  </div>

                  <div className="mt-6 flex flex-wrap items-center gap-3">
                    <Button className="h-11 rounded-full px-6" onClick={handleSeed} disabled={!newTaskTitle.trim()}>
                      <PlusCircle className="mr-2 h-4 w-4" /> 写入任务
                    </Button>
                    <div className="text-sm text-slate-500">
                      写入后将自动进入 `分析任务` 表，随后沉淀 `证据链`、`综合报告` 与 `产出评审`。
                    </div>
                  </div>
                </section>

                <section className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Template Center</p>
                      <h2 className="mt-2 text-xl font-semibold text-slate-950">模板配置中心</h2>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                        启用 {templateOverview.total} 个
                      </div>
                      {templateRouteChips.map(([route, count]) => (
                        <div
                          key={route}
                          className={`rounded-full border px-3 py-1 text-xs ${ROUTE_STYLE[route] || 'border-slate-200 bg-slate-50 text-slate-600'}`}
                        >
                          {route} {count}
                        </div>
                      ))}
                    </div>
                  </div>
                  {activeTemplates.length === 0 ? (
                    <div className="mt-5">
                      <EmptyState text="当前还没有启用模板。setup 后会自动创建默认模板，你也可以在多维表格中继续维护。" />
                    </div>
                  ) : (
                    <div className="mt-5 space-y-3">
                      {activeTemplates.slice(0, 5).map((record) => {
                        const route = textValue(record.fields?.适用工作流路由);
                        const purpose = textValue(record.fields?.适用输出目的);
                        const isSelected = selectedTemplateId === record.record_id;
                        return (
                          <div
                            key={record.record_id}
                            className={`rounded-[22px] border p-4 ${isSelected ? 'border-violet-300 bg-violet-50/70' : 'border-slate-200 bg-slate-50/80'}`}
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700">
                                {textValue(record.fields?.模板名称) || '未命名模板'}
                              </span>
                              {route && (
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${ROUTE_STYLE[route] || 'border-slate-200 bg-white text-slate-600'}`}>
                                  {route}
                                </span>
                              )}
                              {purpose && (
                                <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${PURPOSE_STYLE[purpose] || 'border-slate-200 bg-white text-slate-600'}`}>
                                  {purpose}
                                </span>
                              )}
                            </div>
                            <div className="mt-3 text-sm leading-7 text-slate-700">
                              {textValue(record.fields?.模板说明) || '暂无模板说明'}
                            </div>
                            <div className="mt-3 grid gap-2 text-xs text-slate-500">
                              <div>默认汇报对象：{textValue(record.fields?.默认汇报对象) || '未指定'}</div>
                              <div>默认拍板负责人：{textValue(record.fields?.默认拍板负责人) || '未指定'}</div>
                              <div>默认执行负责人：{textValue(record.fields?.默认执行负责人) || '未指定'}</div>
                              <div>默认复核负责人：{textValue(record.fields?.默认复核负责人) || '未指定'}</div>
                              <div>默认复盘负责人：{textValue(record.fields?.默认复盘负责人) || '未指定'}</div>
                            </div>
                            <div className="mt-3 grid gap-3 md:grid-cols-2">
                              <div className="rounded-2xl border border-white/80 bg-white/90 p-3 text-xs leading-6 text-slate-600">
                                <div className="mb-1 font-medium text-slate-900">汇报模板</div>
                                <div className="whitespace-pre-line">{textValue(record.fields?.汇报模板) || '未配置'}</div>
                              </div>
                              <div className="rounded-2xl border border-white/80 bg-white/90 p-3 text-xs leading-6 text-slate-600">
                                <div className="mb-1 font-medium text-slate-900">执行模板</div>
                                <div className="whitespace-pre-line">{textValue(record.fields?.执行模板) || '未配置'}</div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>

                <section className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Live Stream</p>
                      <h2 className="mt-2 text-xl font-semibold text-slate-950">实时进度</h2>
                    </div>
                    <div className={`rounded-full px-3 py-1 text-xs font-medium ${running ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'}`}>
                      {running ? 'SSE Live' : 'Idle'}
                    </div>
                  </div>
                  <div className="mt-5 space-y-3">
                    {liveFeed.length === 0 ? (
                      <EmptyState text="当前没有实时事件。启动调度并让任务进入分析中后，这里会显示 wave 推进与完成事件。" />
                    ) : (
                      liveFeed.map((event) => (
                        <div key={`${event.taskId}-${event.updatedAt}`} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-sm font-medium text-slate-950">{event.taskId.slice(0, 8)}</div>
                            <div className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${event.status === 'done' ? 'bg-emerald-100 text-emerald-700' : event.status === 'error' ? 'bg-rose-100 text-rose-700' : 'bg-sky-100 text-sky-700'}`}>
                              {event.status === 'done' ? '完成' : event.status === 'error' ? '异常' : '推进中'}
                            </div>
                          </div>
                          <p className="mt-2 text-sm leading-6 text-slate-600">{event.stage}</p>
                          <div className="mt-3 flex items-center justify-between text-xs text-slate-500">
                            <span>{formatRelativeTime(event.updatedAt)}</span>
                            <span>{Math.round(event.progress * 100)}%</span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>
            </section>

            <section className="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
              <div className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                <div className="flex items-end justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Portfolio Board</p>
                    <h2 className="mt-2 text-2xl font-semibold text-slate-950">任务组合看板</h2>
                    <p className="mt-2 text-sm leading-6 text-slate-600">
                      任务卡不只是排队，而是按状态、目标对象、数据资产和交付结果来组织整个分析生产线。
                    </p>
                  </div>
                  <div className="rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm text-slate-600">
                    共 {tasks.length} 条任务
                  </div>
                </div>

                <div className="mt-6 grid gap-4 xl:grid-cols-2">
                  {STATUS_ORDER.map((status) => {
                    const grouped = laneTasks(tasks, status);
                    const style = STATUS_STYLE[status];
                    return (
                      <div key={status} className={`rounded-[24px] border border-slate-200 bg-gradient-to-br ${style.lane} p-4`}>
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className={`inline-flex rounded-full px-3 py-1 text-xs font-medium ${style.chip}`}>{status}</div>
                            <div className="mt-3 text-lg font-semibold text-slate-950">{style.label}</div>
                          </div>
                          <div className="text-right">
                            <div className="text-3xl font-semibold text-slate-950">{grouped.length}</div>
                            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Tasks</div>
                          </div>
                        </div>

                        {grouped.length === 0 ? (
                          <div className="mt-5">
                            <EmptyState text="当前暂无该状态任务。" />
                          </div>
                        ) : (
                          <div className="mt-5 space-y-3">
                            {grouped.slice(0, 4).map((task) => {
                              const purpose = textValue(task.fields?.输出目的);
                              const stage = textValue(task.fields?.当前阶段);
                              const live = liveEvents[task.record_id];
                              const reviewAction = taskReviewAction(task, latestReviewByTitle.get(taskTitle(task)) || null);
                              const readinessScore = taskReadinessScore(task, latestReviewByTitle.get(taskTitle(task)) || null);
                              const progress = live ? Math.max(safeProgress(task.fields?.进度), live.progress * 100) : safeProgress(task.fields?.进度);
                              const isSelected = task.record_id === selectedTask?.record_id;
                              return (
                                <button
                                  key={task.record_id}
                                  type="button"
                                  onClick={() => setSelectedTaskId(task.record_id)}
                                  className={`w-full rounded-2xl border p-4 text-left shadow-sm transition ${isSelected ? 'border-teal-300 bg-white/96' : 'border-white/80 bg-white/88 hover:border-slate-300'}`}
                                >
                                  <div className="flex items-start justify-between gap-3">
                                    <div className="min-w-0 flex-1">
                                      <div className="text-sm font-semibold leading-6 text-slate-950">
                                        {taskTitle(task) || '未命名任务'}
                                      </div>
                                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                                        {purpose && (
                                          <span className={`rounded-full border px-2.5 py-1 ${PURPOSE_STYLE[purpose] || 'border-slate-200 bg-slate-50 text-slate-600'}`}>
                                            {purpose}
                                          </span>
                                        )}
                                        {reviewAction && (
                                          <span className={`rounded-full border px-2.5 py-1 ${RECOMMENDATION_STYLE[reviewAction] || 'border-slate-200 bg-white text-slate-600'}`}>
                                            {reviewAction}
                                          </span>
                                        )}
                                        {textValue(task.fields?.优先级) && (
                                          <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1">
                                            {textValue(task.fields?.优先级)}
                                          </span>
                                        )}
                                        {textValue(task.fields?.目标对象) && (
                                          <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1">
                                            给 {textValue(task.fields?.目标对象)}
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                    <div className="text-right text-xs text-slate-500">
                                      {live ? formatRelativeTime(live.updatedAt) : '等待更新'}
                                    </div>
                                  </div>

                                  {(stage || live?.stage) && (
                                    <div className="mt-3 text-sm leading-6 text-slate-600">
                                      {live && <span className="text-teal-600">● </span>}
                                      {live?.stage || stage}
                                    </div>
                                  )}

                                  <div className="mt-4">
                                    <Progress value={progress} className="h-2" />
                                    <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                                      <span>{textValue(task.fields?.引用数据集) ? `数据集：${textValue(task.fields?.引用数据集)}` : `证据 ${numberValue(task.fields?.证据条数)} 条`}</span>
                                      <span>{progress.toFixed(0)}% · 就绪度 {readinessScore}/5</span>
                                    </div>
                                  </div>
                                </button>
                              );
                            })}
                            {grouped.length > 4 && (
                              <div className="px-2 text-xs text-slate-500">
                                还有 {grouped.length - 4} 条任务未展开显示。
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="space-y-6">
                <section className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Workflow Contract</p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-950">交付结构</h2>
                  <div className="mt-5 space-y-3">
                    {[
                      { title: '任务卡', desc: '输入业务目标、受众、约束和数据引用，减少 prompt 漂移。', icon: Briefcase },
                      { title: '证据链', desc: '把结论拆成结构化 evidence，区分真实数据、基准估算与上游引用。', icon: FileSearch },
                      { title: 'CEO 决策单', desc: '输出必须拍板、可授权、需补数、立即执行四类行动。', icon: ShieldAlert },
                      { title: '产出评审', desc: '自动 reviewer 评估真实性、决策性、可执行性和闭环准备度。', icon: FileCheck2 },
                    ].map((item) => {
                      const Icon = item.icon;
                      return (
                        <div key={item.title} className="flex gap-3 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
                          <div className="rounded-2xl border border-white bg-white p-3 shadow-sm">
                            <Icon className="h-4 w-4 text-teal-700" />
                          </div>
                          <div>
                            <div className="text-sm font-medium text-slate-950">{item.title}</div>
                            <p className="mt-1 text-sm leading-6 text-slate-600">{item.desc}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>

                <section className="rounded-[28px] border border-white/70 bg-white/90 p-6 shadow-[0_20px_64px_rgba(15,23,42,0.06)]">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Review Overview</p>
                  <h2 className="mt-2 text-xl font-semibold text-slate-950">评审分布</h2>
                  <div className="mt-5 grid gap-3">
                    {[
                      { label: '直接采用', value: reviewOverview.directAdopt, style: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
                      { label: '补数后复核', value: reviewOverview.recheck, style: 'border-amber-200 bg-amber-50 text-amber-700' },
                      { label: '建议重跑', value: reviewOverview.rerun, style: 'border-rose-200 bg-rose-50 text-rose-700' },
                    ].map((item) => (
                      <div key={item.label} className={`rounded-2xl border p-4 ${item.style}`}>
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-sm font-medium">{item.label}</span>
                          <span className="text-2xl font-semibold">{item.value}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
