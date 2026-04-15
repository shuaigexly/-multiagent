import { ConfigProvider, Layout, Menu } from 'antd';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import zhCN from 'antd/locale/zh_CN';
import Workbench from './pages/Workbench';
import ResultView from './pages/ResultView';
import History from './pages/History';
import { RobotOutlined, HistoryOutlined } from '@ant-design/icons';

const { Header, Content } = Layout;

function AppContent() {
  const navigate = useNavigate();
  const location = useLocation();
  const selectedKey = location.pathname.startsWith('/history') ? 'history' : 'workbench';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center', padding: '0 24px', gap: 16 }}>
        <div style={{ color: '#fff', fontWeight: 700, fontSize: 16, whiteSpace: 'nowrap' }}>
          🤖 飞书 AI 工作台
        </div>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[selectedKey]}
          style={{ flex: 1, minWidth: 0 }}
          items={[
            { key: 'workbench', icon: <RobotOutlined />, label: '工作台', onClick: () => navigate('/') },
            { key: 'history', icon: <HistoryOutlined />, label: '历史任务', onClick: () => navigate('/history') },
          ]}
        />
      </Header>
      <Content style={{ background: '#f5f5f5' }}>
        <Routes>
          <Route path="/" element={<Workbench />} />
          <Route path="/results/:taskId" element={<ResultView />} />
          <Route path="/history" element={<History />} />
        </Routes>
      </Content>
    </Layout>
  );
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
    </ConfigProvider>
  );
}
