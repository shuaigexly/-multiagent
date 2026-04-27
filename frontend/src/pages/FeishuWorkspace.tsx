import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  CalendarDays,
  CheckSquare,
  FileText,
  Inbox,
  Loader2,
  MessageSquare,
  Settings,
  Users,
} from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import {
  getCalendarEvents,
  getChats,
  getDriveFiles,
  getFeishuTasks,
} from '@/services/feishu';
import { getConfig } from '@/services/config';
import type {
  CalendarEvent,
  DriveFile,
  FeishuChat,
  FeishuTask,
} from '@/services/feishu';

type TabKey = 'drive' | 'calendar' | 'tasks' | 'chats';

const FILE_TYPE_MAP: Record<string, string> = {
  doc: '文档',
  sheet: '表格',
  bitable: '多维表格',
  wiki: '知识库',
  file: '文件',
};

function formatDateTime(value: string | null) {
  if (!value) return null;
  const ts = Number(value);
  if (Number.isNaN(ts)) return null;
  return new Date(ts * 1000);
}

function formatCalendarRange(start: string | null, end: string | null) {
  const startDate = formatDateTime(start);
  const endDate = formatDateTime(end);
  if (!startDate || !endDate) return '时间未知';

  const datePart = startDate.toLocaleDateString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
  });
  const startPart = startDate.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  const endPart = endDate.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });

  return `${datePart} ${startPart} – ${endPart}`;
}

function formatDisplayTime(value: string | null) {
  const date = formatDateTime(value);
  if (!date) return null;
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center py-20 gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      加载中...
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
      <Inbox className="h-8 w-8 text-muted-foreground" />
      <div className="text-base font-medium text-foreground">暂无数据</div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{message}</div>;
}

export default function FeishuWorkspace() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabKey>('drive');
  const [feishuConfigured, setFeishuConfigured] = useState<boolean | null>(null);

  const [driveFiles, setDriveFiles] = useState<DriveFile[]>([]);
  const [driveLoading, setDriveLoading] = useState(false);
  const [driveError, setDriveError] = useState<string | null>(null);
  const [driveLoaded, setDriveLoaded] = useState(false);

  const [calendarEvents, setCalendarEvents] = useState<CalendarEvent[]>([]);
  const [calendarLoading, setCalendarLoading] = useState(false);
  const [calendarError, setCalendarError] = useState<string | null>(null);
  const [calendarLoaded, setCalendarLoaded] = useState(false);

  const [tasks, setTasks] = useState<FeishuTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState<string | null>(null);
  const [tasksLoaded, setTasksLoaded] = useState(false);

  const [chats, setChats] = useState<FeishuChat[]>([]);
  const [chatsLoading, setChatsLoading] = useState(false);
  const [chatsError, setChatsError] = useState<string | null>(null);
  const [chatsLoaded, setChatsLoaded] = useState(false);

  useEffect(() => {
    getConfig().then(cfg => {
      setFeishuConfigured(Boolean(cfg.feishu_app_id?.set && cfg.feishu_app_secret?.set));
    }).catch(() => setFeishuConfigured(false));
  }, []);

  useEffect(() => {
    if (feishuConfigured !== true) return;
    if (activeTab === 'drive' && !driveLoaded && !driveLoading) {
      setDriveLoading(true);
      setDriveError(null);
      getDriveFiles()
        .then(setDriveFiles)
        .catch(() => setDriveError('加载文档失败'))
        .finally(() => {
          setDriveLoading(false);
          setDriveLoaded(true);
        });
    }

    if (activeTab === 'calendar' && !calendarLoaded && !calendarLoading) {
      setCalendarLoading(true);
      setCalendarError(null);
      getCalendarEvents()
        .then(setCalendarEvents)
        .catch(() => setCalendarError('加载日历失败'))
        .finally(() => {
          setCalendarLoading(false);
          setCalendarLoaded(true);
        });
    }

    if (activeTab === 'tasks' && !tasksLoaded && !tasksLoading) {
      setTasksLoading(true);
      setTasksError(null);
      getFeishuTasks()
        .then(setTasks)
        .catch(() => setTasksError('加载任务失败'))
        .finally(() => {
          setTasksLoading(false);
          setTasksLoaded(true);
        });
    }

    if (activeTab === 'chats' && !chatsLoaded && !chatsLoading) {
      setChatsLoading(true);
      setChatsError(null);
      getChats()
        .then(setChats)
        .catch(() => setChatsError('加载群聊失败'))
        .finally(() => {
          setChatsLoading(false);
          setChatsLoaded(true);
        });
    }
  }, [
    activeTab,
    calendarLoaded,
    calendarLoading,
    chatsLoaded,
    chatsLoading,
    driveLoaded,
    driveLoading,
    feishuConfigured,
    tasksLoaded,
    tasksLoading,
  ]);

  if (feishuConfigured === null) return (
    <div className="flex items-center justify-center min-h-[60vh] gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />加载中...
    </div>
  );

  if (!feishuConfigured) return (
    <div className="max-w-4xl mx-auto px-5 py-6">
      <div className="mb-5">
        <h1 className="text-xl font-semibold text-foreground">飞书工作区</h1>
        <p className="mt-1 text-sm text-muted-foreground">查看已授权飞书中的文档、日历、任务和群聊</p>
      </div>
      <div className="flex flex-col items-center justify-center py-20 gap-4 text-center rounded-lg border border-dashed border-border bg-card">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-accent">
          <Settings className="h-6 w-6 text-muted-foreground" />
        </div>
        <div className="space-y-1">
          <div className="text-base font-medium text-foreground">飞书未配置</div>
          <p className="text-sm text-muted-foreground max-w-xs">
            需要配置飞书 App ID 和 App Secret 才能查看飞书工作区数据
          </p>
        </div>
        <Button onClick={() => navigate('/settings')}>
          前往设置配置飞书
        </Button>
      </div>
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-foreground">飞书工作区</h1>
        <p className="mt-1 text-sm text-muted-foreground">查看已授权飞书中的文档、日历、任务和群聊</p>
      </div>

      <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as TabKey)} className="space-y-4">
        <TabsList className="h-auto w-full justify-start rounded-none border-b border-border bg-transparent p-0">
          <TabsTrigger
            value="drive"
            className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            文档
          </TabsTrigger>
          <TabsTrigger
            value="calendar"
            className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            日历
          </TabsTrigger>
          <TabsTrigger
            value="tasks"
            className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            任务
          </TabsTrigger>
          <TabsTrigger
            value="chats"
            className="rounded-none border-b-2 border-transparent bg-transparent px-4 py-2 text-sm text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
          >
            群聊
          </TabsTrigger>
        </TabsList>

        <TabsContent value="drive">
          {driveLoading ? (
            <LoadingState />
          ) : driveError ? (
            <ErrorState message={driveError} />
          ) : driveFiles.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-2.5">
              {driveFiles.map((file) => {
                const clickable = Boolean(file.url);
                return (
                  <div
                    key={file.token}
                    className={`flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-sm transition-all ${clickable ? 'cursor-pointer hover:bg-secondary/30 hover:shadow-md' : ''}`}
                    onClick={() => clickable && window.open(file.url!, '_blank', 'noopener,noreferrer')}
                    role={clickable ? 'button' : undefined}
                    tabIndex={clickable ? 0 : -1}
                    onKeyDown={(event) => {
                      if (!clickable) return;
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        window.open(file.url!, '_blank', 'noopener,noreferrer');
                      }
                    }}
                  >
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-foreground truncate">{file.name}</p>
                        <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground">
                          {FILE_TYPE_MAP[file.type] || file.type}
                        </span>
                      </div>
                      {file.modified_time && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          最近更新 {formatDisplayTime(file.modified_time)}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        <TabsContent value="calendar">
          {calendarLoading ? (
            <LoadingState />
          ) : calendarError ? (
            <ErrorState message={calendarError} />
          ) : calendarEvents.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-2.5">
              {calendarEvents.map((event) => (
                <div
                  key={event.event_id}
                  className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-sm transition-all hover:bg-secondary/30 hover:shadow-md"
                >
                  <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground truncate">{event.summary}</p>
                      {event.attendees_count > 0 && (
                        <span className="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground">
                          <Users className="h-3 w-3" />
                          {event.attendees_count}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {formatCalendarRange(event.start_time, event.end_time)}
                    </p>
                    {event.location && (
                      <p className="text-xs text-muted-foreground mt-0.5 truncate">{event.location}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="tasks">
          {tasksLoading ? (
            <LoadingState />
          ) : tasksError ? (
            <ErrorState message={tasksError} />
          ) : tasks.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-2.5">
              {tasks.map((task) => (
                <div
                  key={task.guid}
                  className={`flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-sm transition-all hover:bg-secondary/30 hover:shadow-md ${task.completed ? 'opacity-50' : ''}`}
                >
                  <CheckSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className={`text-sm font-medium text-foreground truncate ${task.completed ? 'line-through' : ''}`}>
                        {task.summary}
                      </p>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${task.completed ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}
                      >
                        {task.completed ? '已完成' : '待完成'}
                      </span>
                    </div>
                    {task.due && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        截止时间 {formatDisplayTime(task.due)}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="chats">
          {chatsLoading ? (
            <LoadingState />
          ) : chatsError ? (
            <ErrorState message={chatsError} />
          ) : chats.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="space-y-2.5">
              {chats.map((chat) => (
                <div
                  key={chat.chat_id}
                  className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-sm transition-all hover:bg-secondary/30 hover:shadow-md"
                >
                  <MessageSquare className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground truncate">{chat.name}</p>
                      {chat.chat_type && (
                        <span className="rounded bg-secondary px-1.5 py-0.5 text-[11px] text-secondary-foreground">
                          {chat.chat_type}
                        </span>
                      )}
                    </div>
                    {chat.description && (
                      <p className="text-xs text-muted-foreground mt-0.5 truncate">{chat.description}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
