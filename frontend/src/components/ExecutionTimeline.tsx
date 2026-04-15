import { Timeline, Spin, Tag } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import type { SSEEvent } from '../services/types';

interface Props {
  events: SSEEvent[];
  status: 'running' | 'done' | 'failed' | 'idle';
}

const EVENT_COLORS: Record<string, string> = {
  'task.recognized': 'blue',
  'context.retrieved': 'cyan',
  'module.started': 'processing',
  'module.completed': 'green',
  'module.failed': 'red',
  'feishu.writing': 'purple',
  'task.done': 'green',
  'task.error': 'red',
};

function EventIcon({ type, status }: { type: string; status: string }) {
  if (type === 'task.done') return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
  if (type === 'task.error' || type === 'module.failed') return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
  if (type === 'module.started' && status === 'running') return <LoadingOutlined style={{ color: '#1677ff' }} />;
  return <InfoCircleOutlined style={{ color: '#1677ff' }} />;
}

export default function ExecutionTimeline({ events, status }: Props) {
  if (events.length === 0 && status === 'idle') return null;

  const items = events.map((e) => ({
    dot: <EventIcon type={e.event_type} status={status} />,
    color: EVENT_COLORS[e.event_type] || 'blue',
    children: (
      <div>
        <span style={{ fontSize: 14 }}>{e.message}</span>
        {e.agent_name && (
          <Tag style={{ marginLeft: 8, fontSize: 11 }}>{e.agent_name}</Tag>
        )}
      </div>
    ),
  }));

  if (status === 'running') {
    items.push({
      dot: <Spin indicator={<LoadingOutlined />} size="small" />,
      color: 'blue',
      children: <span style={{ color: '#8c8c8c' }}>执行中...</span>,
    });
  }

  return (
    <div style={{ padding: '16px 0' }}>
      <Timeline items={items} />
    </div>
  );
}
