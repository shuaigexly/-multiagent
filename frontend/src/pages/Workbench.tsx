import { useState, useEffect } from 'react';
import {
  Button, Card, Checkbox, Col, Collapse, Divider, Input, Row,
  Space, Spin, Tag, Typography, Upload, message, Alert,
} from 'antd';
import { InboxOutlined, ThunderboltOutlined } from '@ant-design/icons';
import type { UploadFile } from 'antd';
import {
  submitTask, confirmTask, listAgents, createSSEConnection,
} from '../services/api';
import type { AgentInfo, SSEEvent, TaskPlanResponse } from '../services/types';
import ModuleCard from '../components/ModuleCard';
import ExecutionTimeline from '../components/ExecutionTimeline';
import { useNavigate } from 'react-router-dom';

const { TextArea } = Input;
const { Title, Paragraph, Text } = Typography;

const PRESET_COMBOS = [
  { label: '经营分析', modules: ['data_analyst', 'finance_advisor', 'ceo_assistant'] },
  { label: '立项评估', modules: ['product_manager', 'finance_advisor', 'ceo_assistant'] },
  { label: '内容增长', modules: ['seo_advisor', 'content_manager', 'operations_manager'] },
  { label: '综合分析', modules: ['data_analyst', 'operations_manager', 'ceo_assistant'] },
];

type Step = 'input' | 'planning' | 'confirm' | 'running' | 'done';

export default function Workbench() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [inputText, setInputText] = useState('');
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [step, setStep] = useState<Step>('input');
  const [plan, setPlan] = useState<TaskPlanResponse | null>(null);
  const [selectedModules, setSelectedModules] = useState<string[]>([]);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);

  useEffect(() => {
    listAgents().then(setAgents).catch(console.error);
  }, []);

  const toggleModule = (id: string) => {
    setSelectedModules((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]
    );
  };

  const handleSubmit = async () => {
    if (!inputText.trim() && fileList.length === 0) {
      message.error('请输入任务描述或上传文件');
      return;
    }
    setLoading(true);
    setStep('planning');
    try {
      const file = fileList[0]?.originFileObj as File | undefined;
      const result = await submitTask(inputText, file);
      setPlan(result);
      setTaskId(result.task_id);
      setSelectedModules(result.selected_modules);
      setStep('confirm');
    } catch (e) {
      message.error('任务识别失败，请重试');
      setStep('input');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!taskId || selectedModules.length === 0) {
      message.error('请至少选择一个分析模块');
      return;
    }
    setLoading(true);
    setStep('running');
    setEvents([]);
    try {
      await confirmTask(taskId, selectedModules);
      // 开始监听 SSE
      const es = createSSEConnection(taskId);
      es.onmessage = (e) => {
        const data = JSON.parse(e.data) as SSEEvent & { status?: string };
        if (data.event_type === 'stream.end') {
          es.close();
          setStep('done');
          setLoading(false);
          if (data.status === 'done') {
            message.success('分析完成！');
          }
        } else if (data.event_type !== 'stream.timeout') {
          setEvents((prev) => [...prev, data as SSEEvent]);
        }
      };
      es.onerror = () => {
        es.close();
        setLoading(false);
        setStep('done');
      };
    } catch (e) {
      message.error('执行失败');
      setStep('confirm');
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px 16px' }}>
      <Title level={2} style={{ marginBottom: 4 }}>飞书 AI 工作台</Title>
      <Paragraph type="secondary">
        描述你的任务，AI 自动识别类型、调用最合适的分析模块、结果同步飞书
      </Paragraph>

      {/* Step 1: 输入 */}
      <Card style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0, marginBottom: 12 }}>① 描述任务</Title>
        <TextArea
          rows={4}
          placeholder="例如：分析本月经营数据，重点看收入趋势和成本风险"
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          disabled={step !== 'input'}
        />
        <div style={{ marginTop: 12 }}>
          <Upload.Dragger
            fileList={fileList}
            beforeUpload={(file) => { setFileList([file as unknown as UploadFile]); return false; }}
            onRemove={() => setFileList([])}
            disabled={step !== 'input'}
            accept=".csv,.txt,.xlsx"
            maxCount={1}
          >
            <p className="ant-upload-drag-icon"><InboxOutlined /></p>
            <p className="ant-upload-text">可附加数据文件（CSV、TXT）</p>
          </Upload.Dragger>
        </div>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          style={{ marginTop: 12 }}
          loading={loading && step === 'planning'}
          disabled={step !== 'input'}
          onClick={handleSubmit}
          size="large"
          block
        >
          识别任务
        </Button>
      </Card>

      {/* Step 2: 确认规划 */}
      {(step === 'confirm' || step === 'running' || step === 'done') && plan && (
        <Card style={{ marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0, marginBottom: 8 }}>② 确认分析模块</Title>
          <Alert
            message={
              <span>
                识别为 <Tag color="blue">{plan.task_type_label}</Tag>
                <Text type="secondary" style={{ fontSize: 13 }}>{plan.reasoning}</Text>
              </span>
            }
            type="info"
            style={{ marginBottom: 12 }}
          />
          <div style={{ marginBottom: 8 }}>
            <Text type="secondary" style={{ marginRight: 8 }}>快捷组合：</Text>
            {PRESET_COMBOS.map((c) => (
              <Button
                key={c.label}
                size="small"
                style={{ marginRight: 4, marginBottom: 4 }}
                onClick={() => setSelectedModules(c.modules)}
                disabled={step !== 'confirm'}
              >
                {c.label}
              </Button>
            ))}
          </div>
          <Row gutter={[12, 12]}>
            {agents.map((agent) => (
              <Col key={agent.id} xs={24} sm={12} md={8}>
                <ModuleCard
                  agent={agent}
                  selected={selectedModules.includes(agent.id)}
                  onToggle={step === 'confirm' ? toggleModule : () => {}}
                />
              </Col>
            ))}
          </Row>
          <Button
            type="primary"
            style={{ marginTop: 16 }}
            loading={loading && step === 'running'}
            disabled={step !== 'confirm' || selectedModules.length === 0}
            onClick={handleConfirm}
            size="large"
            block
          >
            确认执行（{selectedModules.length} 个模块）
          </Button>
        </Card>
      )}

      {/* Step 3: 执行进度 */}
      {(step === 'running' || step === 'done') && (
        <Card style={{ marginBottom: 16 }}>
          <Title level={4} style={{ margin: 0, marginBottom: 8 }}>③ 执行进度</Title>
          <ExecutionTimeline events={events} status={step === 'running' ? 'running' : 'done'} />
          {step === 'done' && taskId && (
            <Button
              type="primary"
              style={{ marginTop: 8 }}
              onClick={() => navigate(`/results/${taskId}`)}
            >
              查看完整结果 →
            </Button>
          )}
        </Card>
      )}
    </div>
  );
}
