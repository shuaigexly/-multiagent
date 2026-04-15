import { Card, Tag, Checkbox } from 'antd';
import type { AgentInfo } from '../services/types';

interface Props {
  agent: AgentInfo;
  selected: boolean;
  onToggle: (id: string) => void;
}

const MODULE_COLORS: Record<string, string> = {
  data_analyst: 'blue',
  finance_advisor: 'green',
  seo_advisor: 'orange',
  content_manager: 'purple',
  product_manager: 'cyan',
  operations_manager: 'red',
  ceo_assistant: 'gold',
};

export default function ModuleCard({ agent, selected, onToggle }: Props) {
  return (
    <Card
      hoverable
      onClick={() => onToggle(agent.id)}
      style={{
        cursor: 'pointer',
        border: selected ? '2px solid #1677ff' : '1px solid #d9d9d9',
        borderRadius: 8,
        transition: 'all 0.2s',
      }}
      bodyStyle={{ padding: 16 }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <Tag color={MODULE_COLORS[agent.id] || 'default'}>{agent.name}</Tag>
            <Checkbox checked={selected} onChange={() => onToggle(agent.id)} />
          </div>
          <p style={{ margin: 0, color: '#595959', fontSize: 13 }}>{agent.description}</p>
          <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {agent.suitable_for.map((tag) => (
              <Tag key={tag} style={{ fontSize: 11 }}>{tag}</Tag>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
