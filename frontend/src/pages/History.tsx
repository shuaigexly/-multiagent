import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, List, Tag, Typography, Spin, message } from 'antd';
import { listTasks } from '../services/api';
import type { TaskListItem } from '../services/types';

const { Title, Text } = Typography;

const STATUS_LABELS: Record<string, string> = {
  done: '完成',
  running: '执行中',
  failed: '失败',
  pending: '等待中',
  planning: '规划中',
};
const STATUS_COLORS: Record<string, string> = {
  done: 'green', running: 'blue', failed: 'red', pending: 'orange', planning: 'cyan',
};

export default function History() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listTasks()
      .then(setTasks)
      .catch(() => message.error('加载历史记录失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Spin fullscreen />;

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={3}>历史任务</Title>
      <List
        dataSource={tasks}
        locale={{ emptyText: '暂无历史任务' }}
        renderItem={(task) => (
          <List.Item
            actions={[
              <Button
                type="link"
                onClick={() => navigate(`/results/${task.id}`)}
                disabled={task.status === 'planning' || task.status === 'pending'}
              >
                查看结果
              </Button>,
            ]}
          >
            <List.Item.Meta
              title={
                <span>
                  <Tag color={STATUS_COLORS[task.status]}>{STATUS_LABELS[task.status] || task.status}</Tag>
                  {task.task_type_label && <Tag>{task.task_type_label}</Tag>}
                </span>
              }
              description={
                <div>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {task.input_text || '（文件上传）'}
                  </Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {new Date(task.created_at).toLocaleString('zh-CN')}
                  </Text>
                </div>
              }
            />
          </List.Item>
        )}
      />
    </div>
  );
}
