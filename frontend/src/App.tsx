import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import Workbench from './pages/Workbench';
import ResultView from './pages/ResultView';
import History from './pages/History';

function Nav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const onHistory = pathname.startsWith('/history');

  return (
    <header
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        background: 'rgba(5,5,8,0.9)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 var(--space-6)',
        height: 48,
        gap: 'var(--space-6)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontWeight: 700,
          fontSize: 13,
          letterSpacing: '-0.01em',
          color: 'var(--text-primary)',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            width: 20,
            height: 20,
            background: 'var(--accent)',
            borderRadius: 'var(--radius-sm)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            color: '#000',
            fontWeight: 700,
          }}
        >
          AI
        </span>
        飞书工作台
      </div>

      <nav style={{ display: 'flex', gap: 2, flex: 1 }}>
        {([
          { label: '工作台', path: '/', active: !onHistory },
          { label: '历史任务', path: '/history', active: onHistory },
        ] as const).map(({ label, path, active }) => (
          <button
            key={path}
            onClick={() => navigate(path)}
            className="btn btn-ghost btn-sm"
            style={{
              color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
              borderColor: active ? 'var(--border)' : 'transparent',
              background: active ? 'var(--bg-elevated)' : 'transparent',
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
        <div className="status-dot status-dot-pulse" style={{ background: 'var(--success)' }} />
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>ONLINE</span>
      </div>
    </header>
  );
}

function AppContent() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100svh' }}>
      <Nav />
      <main style={{ flex: 1 }}>
        <Routes>
          <Route path="/" element={<Workbench />} />
          <Route path="/results/:taskId" element={<ResultView />} />
          <Route path="/history" element={<History />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}
