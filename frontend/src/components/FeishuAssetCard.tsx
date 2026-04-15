import { Card, Tag, Button, Space } from 'antd';
import {
  FileTextOutlined,
  TableOutlined,
  MessageOutlined,
  CheckSquareOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import type { PublishedAsset } from '../services/types';

interface Props {
  asset: PublishedAsset;
}

const ASSET_ICONS: Record<string, React.ReactNode> = {
  doc: <FileTextOutlined />,
  bitable: <TableOutlined />,
  message: <MessageOutlined />,
  task: <CheckSquareOutlined />,
};

const ASSET_COLORS: Record<string, string> = {
  doc: 'blue',
  bitable: 'green',
  message: 'orange',
  task: 'purple',
};

const ASSET_LABELS: Record<string, string> = {
  doc: '飞书文档',
  bitable: '多维表格',
  message: '群消息',
  task: '飞书任务',
};

export default function FeishuAssetCard({ asset }: Props) {
  return (
    <Card size="small" style={{ marginBottom: 8 }}>
      <Space>
        <Tag color={ASSET_COLORS[asset.type] || 'default'} icon={ASSET_ICONS[asset.type]}>
          {ASSET_LABELS[asset.type] || asset.type}
        </Tag>
        <span>{asset.title || asset.type}</span>
        {asset.url && (
          <Button
            type="link"
            size="small"
            icon={<LinkOutlined />}
            href={asset.url}
            target="_blank"
          >
            打开
          </Button>
        )}
      </Space>
    </Card>
  );
}
