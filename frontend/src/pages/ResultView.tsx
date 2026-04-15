import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Button, Card, Collapse, Divider, List, Space, Spin, Tag, Typography,
  Checkbox, message, Modal, Input,
} from 'antd';
import { ArrowLeftOutlined, SendOutlined } from '@ant-design/icons';
import { getTaskResults, publishTask } from '../services/api';
import type { TaskResultsResponse } from '../services/types';
import FeishuAssetCard from '../components/FeishuAssetCard';

const { Title, Paragraph, Text } = Typography;

const STATUS_COLORS: Record<string, string> = {
  done: 'green',
  running: 'blue',
  failed: 'red',
  pending: 'orange',
};

export default function ResultView() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<TaskResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [publishTypes, setPublishTypes] = useState<string[]>(['doc', 'task']);
  const [docTitle, setDocTitle] = useState('');
  const [chatId, setChatId] = useState('');

  useEffect(() => {
    if (!taskId) return;
    getTaskResults(taskId)
      .then(setData)
      .catch(() => message.error('加载结果失败'))
      .finally(() => setLoading(false));
  }, [taskId]);

  const handlePublish = async () => {
    if (!taskId) return;
    setPublishing(true);
    try {
      const result = await publishTask(taskId, publishTypes, {
        docTitle: docTitle || undefined,
        chatId: chatId || undefined,
      });
      message.success(`发布成功，共发布 ${result.published.length} 项`);
      setPublishModalOpen(false);
      // 刷新
      const updated = await getTaskResults(taskId);
      setData(updated);
    } catch (e) {
      message.error('发布失败，请检查飞书配置');
    } finally {
      setPublishing(false);
    }
  };

  if (loading) return <Spin fullscreen />;
  if (!data) return <div style={{ padding: 24 }}>任务不存在</div>;

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px' }}>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回</Button>
        <Title level={3} style={{ margin: 0 }}>
          {data.task_type_label}报告
        </Title>
        <Tag color={STATUS_COLORS[data.status] || 'default'}>{data.status}</Tag>
      </Space>

      {/* 总结 */}
      {data.result_summary && (
        <Card style={{ marginBottom: 16, background: '#f6ffed', borderColor: '#b7eb8f' }}>
          <Title level={5} style={{ margin: 0, marginBottom: 8 }}>核心结论</Title>
          <Paragraph style={{ margin: 0 }}>{data.result_summary}</Paragraph>
        </Card>
      )}

      {/* 各模块结果 */}
      <Collapse
        style={{ marginBottom: 16 }}
        items={data.agent_results.map((r) => ({
          key: r.agent_id,
          label: (
            <Space>
              <Tag>{r.agent_name}</Tag>
              <Text type="secondary">{r.sections.length} 个分析板块</Text>
            </Space>
          ),
          children: (
            <div>
              {r.sections.map((s, i) => (
                <div key={i} style={{ marginBottom: 12 }}>
                  <Text strong>{s.title}</Text>
                  <Paragraph style={{ whiteSpace: 'pre-line', marginTop: 4 }}>
                    {s.content}
                  </Paragraph>
                </div>
              ))}
              {r.action_items.length > 0 && (
                <div>
                  <Divider style={{ margin: '8px 0' }} />
                  <Text strong>行动项</Text>
                  <List
                    size="small"
                    dataSource={r.action_items}
                    renderItem={(item) => <List.Item>• {item}</List.Item>}
                  />
                </div>
              )}
            </div>
          ),
        }))}
      />

      {/* 已发布的飞书资产 */}
      {data.published_assets.length > 0 && (
        <Card title="已同步到飞书" style={{ marginBottom: 16 }}>
          {data.published_assets.map((asset, i) => (
            <FeishuAssetCard key={i} asset={asset} />
          ))}
        </Card>
      )}

      {/* 发布到飞书 */}
      {data.status === 'done' && (
        <Button
          type="primary"
          icon={<SendOutlined />}
          size="large"
          onClick={() => setPublishModalOpen(true)}
          block
        >
          同步到飞书
        </Button>
      )}

      <Modal
        title="选择同步内容"
        open={publishModalOpen}
        onOk={handlePublish}
        confirmLoading={publishing}
        onCancel={() => setPublishModalOpen(false)}
        okText="确认同步"
      >
        <Checkbox.Group
          value={publishTypes}
          onChange={(v) => setPublishTypes(v as string[])}
          style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}
        >
          <Checkbox value="doc">飞书文档（完整分析报告）</Checkbox>
          <Checkbox value="bitable">多维表格（行动建议清单）</Checkbox>
          <Checkbox value="message">群消息（管理摘要）</Checkbox>
          <Checkbox value="task">飞书任务（行动项转任务）</Checkbox>
        </Checkbox.Group>
        <Input
          placeholder="文档标题（可选，默认使用任务类型）"
          value={docTitle}
          onChange={(e) => setDocTitle(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        <Input
          placeholder="群 ID（可选，默认使用配置的群）"
          value={chatId}
          onChange={(e) => setChatId(e.target.value)}
        />
      </Modal>
    </div>
  );
}
