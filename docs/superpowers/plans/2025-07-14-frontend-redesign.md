# Frontend Redesign — Neural Terminal Aesthetic

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completely replace the generic Ant Design frontend with a dark industrial "neural terminal" aesthetic — monospace typography, electric lime accent, dot-grid background, terminal-style interaction patterns.

**Architecture:** Drop all Ant Design component usage from visual layer. Write custom HTML + CSS (CSS custom properties + animations). Keep `services/api.ts` and `services/types.ts` completely untouched. Every page and component is rewritten from scratch following the design system.

**Tech Stack:** React 19, TypeScript, Vite, React Router 7, Axios (unchanged) — Google Fonts (JetBrains Mono), custom CSS variables, CSS-only animations.

---

## Design System

### Colors
```css
--bg-base:      #050508;
--bg-surface:   #0c0c11;
--bg-elevated:  #131318;
--bg-hover:     #1a1a21;
--border:       rgba(255,255,255,0.07);
--border-bright:rgba(255,255,255,0.14);
--text-primary: #eeeef5;
--text-secondary:#7b7b94;
--text-muted:   #3d3d52;
--accent:       #a3ff00;     /* electric lime — primary CTA */
--accent-dim:   rgba(163,255,0,0.12);
--accent-glow:  rgba(163,255,0,0.35);
--info:         #818cf8;     /* indigo — task type badges */
--success:      #34d399;     /* emerald — done state */
--warning:      #fb923c;     /* orange — pending/planning */
--error:        #f87171;     /* red — failed */
--gold:         #fbbf24;     /* amber — CEO/special modules */
```

### Typography
```css
--font: 'JetBrains Mono', 'Noto Sans Mono CJK SC', monospace;
/* Google Font import: JetBrains Mono weights 400, 500, 700 */
```

### Spacing
```css
--space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
--space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px;
--space-12: 48px; --space-16: 64px;
```

### Radii & Shadows
```css
--radius-sm: 2px;
--radius: 4px;
--radius-lg: 6px;
--shadow-lime: 0 0 16px rgba(163,255,0,0.2);
--shadow-card: 0 1px 0 rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.02);
```

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `index.html` | Modify | Add JetBrains Mono Google Font link |
| `src/index.css` | Rewrite | Design system, reset, dot-grid bg, global styles |
| `src/App.tsx` | Rewrite | Shell layout: top nav bar (terminal tabs), router |
| `src/pages/Workbench.tsx` | Rewrite | 3-phase workflow: input → confirm modules → live execution |
| `src/pages/ResultView.tsx` | Rewrite | Mission report: summary + collapsible agent sections + publish |
| `src/pages/History.tsx` | Rewrite | Log table of past missions |
| `src/components/ExecutionTimeline.tsx` | Rewrite | Live terminal log (SSE events as log lines) |
| `src/components/ModuleCard.tsx` | Rewrite | Process-card (htop-style agent entry) |
| `src/components/FeishuAssetCard.tsx` | Rewrite | Compact asset link row |
| `src/services/api.ts` | **DO NOT TOUCH** | API layer |
| `src/services/types.ts` | **DO NOT TOUCH** | Types |

---

## Task 1: Design Foundation (index.html + index.css)

**Files:**
- Modify: `frontend/index.html`
- Rewrite: `frontend/src/index.css`

- [ ] **Step 1: Update index.html to load JetBrains Mono**

```html
<!-- frontend/index.html — replace <head> content: -->
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>飞书 AI 工作台</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 2: Rewrite src/index.css with full design system**

```css
/* src/index.css — full replacement */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg-base:       #050508;
  --bg-surface:    #0c0c11;
  --bg-elevated:   #131318;
  --bg-hover:      #1a1a21;
  --border:        rgba(255,255,255,0.07);
  --border-bright: rgba(255,255,255,0.14);
  --text-primary:  #eeeef5;
  --text-secondary:#7b7b94;
  --text-muted:    #3d3d52;
  --accent:        #a3ff00;
  --accent-dim:    rgba(163,255,0,0.12);
  --accent-glow:   rgba(163,255,0,0.35);
  --info:          #818cf8;
  --success:       #34d399;
  --warning:       #fb923c;
  --error:         #f87171;
  --gold:          #fbbf24;
  --font:          'JetBrains Mono', 'Noto Sans Mono CJK SC', ui-monospace, monospace;
  --radius-sm:     2px;
  --radius:        4px;
  --radius-lg:     6px;
  --space-1: 4px;  --space-2: 8px;   --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px;  --space-8: 32px; --space-10: 40px;
  --space-12: 48px;--space-16: 64px;
  --shadow-card:   0 1px 0 rgba(255,255,255,0.04), inset 0 1px 0 rgba(255,255,255,0.02);
  --shadow-lime:   0 0 20px rgba(163,255,0,0.18);
  --shadow-focus:  0 0 0 2px rgba(163,255,0,0.4);
}

html { font-size: 14px; }

body {
  font-family: var(--font);
  background: var(--bg-base);
  color: var(--text-primary);
  line-height: 1.6;
  min-height: 100svh;
  /* Dot grid background */
  background-image:
    radial-gradient(circle at 1px 1px, rgba(255,255,255,0.04) 1px, transparent 0);
  background-size: 24px 24px;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

#root {
  min-height: 100svh;
  display: flex;
  flex-direction: column;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ── Selection ── */
::selection { background: var(--accent); color: #000; }

/* ── Focus ── */
:focus-visible { outline: none; box-shadow: var(--shadow-focus); }

/* ── Typography ── */
h1, h2, h3, h4, h5, h6 {
  font-family: var(--font);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Animations ── */
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
@keyframes pulse-dot {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.4); opacity: 0.7; }
}
@keyframes scan-line {
  0% { transform: translateY(-100%); opacity: 0; }
  10% { opacity: 0.3; }
  90% { opacity: 0.3; }
  100% { transform: translateY(100vh); opacity: 0; }
}
@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
@keyframes glow-pulse {
  0%, 100% { box-shadow: 0 0 8px rgba(163,255,0,0.2); }
  50%       { box-shadow: 0 0 24px rgba(163,255,0,0.5); }
}
@keyframes progress-fill {
  from { transform: scaleX(0); }
  to   { transform: scaleX(1); }
}

/* ── Shared Component Primitives ── */

/* Card */
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}

/* Button variants */
.btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  font-family: var(--font);
  font-size: 12px;
  font-weight: 500;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-elevated);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s ease;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  white-space: nowrap;
}
.btn:hover:not(:disabled) {
  border-color: var(--border-bright);
  color: var(--text-primary);
  background: var(--bg-hover);
}
.btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.btn-accent {
  background: var(--accent);
  border-color: var(--accent);
  color: #000;
  font-weight: 700;
}
.btn-accent:hover:not(:disabled) {
  background: #b8ff1a;
  border-color: #b8ff1a;
  box-shadow: var(--shadow-lime);
  color: #000;
}
.btn-accent:disabled {
  background: var(--accent);
  border-color: var(--accent);
  color: #000;
  opacity: 0.35;
}
.btn-ghost {
  background: transparent;
  border-color: transparent;
}
.btn-ghost:hover:not(:disabled) {
  background: var(--bg-elevated);
  border-color: var(--border);
}
.btn-lg {
  padding: var(--space-3) var(--space-6);
  font-size: 13px;
}
.btn-sm {
  padding: 3px var(--space-3);
  font-size: 11px;
}
.btn-block { width: 100%; justify-content: center; }

/* Badge / Tag */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 500;
  border-radius: 2px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.badge-accent  { background: var(--accent-dim); color: var(--accent); border: 1px solid rgba(163,255,0,0.2); }
.badge-info    { background: rgba(129,140,248,0.12); color: var(--info); border: 1px solid rgba(129,140,248,0.2); }
.badge-success { background: rgba(52,211,153,0.12); color: var(--success); border: 1px solid rgba(52,211,153,0.2); }
.badge-warning { background: rgba(251,146,60,0.12); color: var(--warning); border: 1px solid rgba(251,146,60,0.2); }
.badge-error   { background: rgba(248,113,113,0.12); color: var(--error); border: 1px solid rgba(248,113,113,0.2); }
.badge-gold    { background: rgba(251,191,36,0.12); color: var(--gold); border: 1px solid rgba(251,191,36,0.2); }
.badge-neutral { background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border); }

/* Textarea / Input */
.input {
  width: 100%;
  font-family: var(--font);
  font-size: 13px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  padding: var(--space-3) var(--space-4);
  transition: border-color 0.15s;
  resize: vertical;
}
.input::placeholder { color: var(--text-muted); }
.input:focus { border-color: var(--border-bright); outline: none; }
.input-focused { border-color: rgba(163,255,0,0.4); box-shadow: 0 0 0 2px rgba(163,255,0,0.1); }

/* Step label */
.step-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  margin-bottom: var(--space-3);
}

/* Loading spinner */
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(163,255,0,0.2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  flex-shrink: 0;
}

/* Status dot */
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot-pulse {
  animation: pulse-dot 1.2s ease-in-out infinite;
}
```

- [ ] **Step 3: Verify no TypeScript errors**

```bash
cd /Users/jassionyang/multiagent-lark/frontend && npx tsc --noEmit
```

Expected: No output (or only pre-existing errors)

---

## Task 2: App Shell (App.tsx)

**Files:**
- Rewrite: `frontend/src/App.tsx`

- [ ] **Step 1: Rewrite App.tsx**

```tsx
// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import Workbench from './pages/Workbench';
import ResultView from './pages/ResultView';
import History from './pages/History';

function Nav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const onHistory = pathname.startsWith('/history');

  return (
    <header style={{
      position: 'sticky', top: 0, zIndex: 100,
      background: 'rgba(5,5,8,0.9)',
      backdropFilter: 'blur(12px)',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: '0 var(--space-6)',
      height: 48,
      gap: 'var(--space-6)',
    }}>
      {/* Logo */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        fontWeight: 700, fontSize: 13, letterSpacing: '-0.01em',
        color: 'var(--text-primary)',
        flexShrink: 0,
      }}>
        <span style={{
          width: 20, height: 20,
          background: 'var(--accent)', borderRadius: 'var(--radius-sm)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, color: '#000', fontWeight: 700,
        }}>AI</span>
        飞书工作台
      </div>

      {/* Nav tabs */}
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

      {/* Status indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
        <div
          className="status-dot status-dot-pulse"
          style={{ background: 'var(--success)' }}
        />
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
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /Users/jassionyang/multiagent-lark/frontend && npx tsc --noEmit
```

---

## Task 3: ModuleCard Component

**Files:**
- Rewrite: `frontend/src/components/ModuleCard.tsx`

- [ ] **Step 1: Rewrite ModuleCard.tsx**

```tsx
// frontend/src/components/ModuleCard.tsx
import type { AgentInfo } from '../services/types';

interface Props {
  agent: AgentInfo;
  selected: boolean;
  onToggle: (id: string) => void;
  disabled?: boolean;
}

const MODULE_ACCENT: Record<string, string> = {
  data_analyst:       'var(--info)',
  finance_advisor:    'var(--success)',
  seo_advisor:        'var(--warning)',
  content_manager:    '#c084fc',
  product_manager:    '#22d3ee',
  operations_manager: 'var(--error)',
  ceo_assistant:      'var(--gold)',
};

const MODULE_PREFIX: Record<string, string> = {
  data_analyst:       'DA',
  finance_advisor:    'FIN',
  seo_advisor:        'SEO',
  content_manager:    'CM',
  product_manager:    'PM',
  operations_manager: 'OPS',
  ceo_assistant:      'CEO',
};

export default function ModuleCard({ agent, selected, onToggle, disabled }: Props) {
  const accent = MODULE_ACCENT[agent.id] || 'var(--text-secondary)';
  const prefix = MODULE_PREFIX[agent.id] || agent.id.slice(0, 3).toUpperCase();

  return (
    <div
      role="checkbox"
      aria-checked={selected}
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && onToggle(agent.id)}
      onKeyDown={(e) => (e.key === ' ' || e.key === 'Enter') && !disabled && onToggle(agent.id)}
      style={{
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        background: selected ? 'var(--bg-elevated)' : 'var(--bg-surface)',
        border: `1px solid ${selected ? accent : 'var(--border)'}`,
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-4)',
        transition: 'all 0.15s ease',
        position: 'relative',
        overflow: 'hidden',
        boxShadow: selected ? `0 0 0 1px ${accent}20, inset 0 0 0 1px ${accent}10` : 'var(--shadow-card)',
        animation: 'fade-in-up 0.2s ease both',
      }}
      onMouseEnter={(e) => {
        if (!disabled && !selected) {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-bright)';
          (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)';
        }
      }}
      onMouseLeave={(e) => {
        if (!disabled && !selected) {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)';
          (e.currentTarget as HTMLElement).style.background = 'var(--bg-surface)';
        }
      }}
    >
      {/* Selected indicator line */}
      {selected && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0,
          height: 2, background: accent,
          borderRadius: 'var(--radius-lg) var(--radius-lg) 0 0',
        }} />
      )}

      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
        {/* Module identifier */}
        <div style={{
          width: 32, height: 32, flexShrink: 0,
          background: `${accent}18`,
          border: `1px solid ${accent}30`,
          borderRadius: 'var(--radius)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 10, fontWeight: 700, color: accent, letterSpacing: '0.05em',
        }}>
          {prefix}
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
            {agent.name}
          </div>
        </div>

        {/* Checkbox indicator */}
        <div style={{
          width: 14, height: 14, flexShrink: 0,
          border: `1.5px solid ${selected ? accent : 'var(--border-bright)'}`,
          borderRadius: 'var(--radius-sm)',
          background: selected ? accent : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          transition: 'all 0.15s',
        }}>
          {selected && (
            <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
              <path d="M1 3L3 5L7 1" stroke="#000" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          )}
        </div>
      </div>

      {/* Description */}
      <p style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 'var(--space-3)' }}>
        {agent.description}
      </p>

      {/* Tags */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {agent.suitable_for.slice(0, 3).map((tag) => (
          <span
            key={tag}
            style={{
              fontSize: 10, padding: '1px 6px',
              background: 'var(--bg-base)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)',
              letterSpacing: '0.03em',
            }}
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}
```

---

## Task 4: ExecutionTimeline Component

**Files:**
- Rewrite: `frontend/src/components/ExecutionTimeline.tsx`

- [ ] **Step 1: Rewrite ExecutionTimeline.tsx**

```tsx
// frontend/src/components/ExecutionTimeline.tsx
import { useEffect, useRef } from 'react';
import type { SSEEvent } from '../services/types';

interface Props {
  events: SSEEvent[];
  status: 'running' | 'done' | 'failed' | 'idle';
}

const EVENT_COLOR: Record<string, string> = {
  'task.recognized':   'var(--info)',
  'context.retrieved': 'var(--info)',
  'module.started':    'var(--warning)',
  'module.completed':  'var(--success)',
  'module.failed':     'var(--error)',
  'feishu.writing':    '#c084fc',
  'task.done':         'var(--accent)',
  'task.error':        'var(--error)',
};

const EVENT_PREFIX: Record<string, string> = {
  'task.recognized':   'PLAN',
  'context.retrieved': 'CTX',
  'module.started':    'RUN',
  'module.completed':  'DONE',
  'module.failed':     'ERR',
  'feishu.writing':    'SYNC',
  'task.done':         'FIN',
  'task.error':        'ERR',
};

function LogLine({ event, index }: { event: SSEEvent; index: number }) {
  const color = EVENT_COLOR[event.event_type] || 'var(--text-secondary)';
  const prefix = EVENT_PREFIX[event.event_type] || event.event_type.split('.').pop()?.toUpperCase() || 'LOG';
  const isSuccess = event.event_type === 'task.done';
  const isError = event.event_type === 'task.error' || event.event_type === 'module.failed';

  return (
    <div
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)',
        padding: 'var(--space-2) 0',
        borderBottom: '1px solid var(--border)',
        animation: `fade-in 0.2s ease both`,
        animationDelay: `${Math.min(index * 30, 200)}ms`,
      }}
    >
      {/* Sequence number */}
      <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0, width: 24, textAlign: 'right', paddingTop: 1 }}>
        {String(event.sequence).padStart(2, '0')}
      </span>

      {/* Connector dot */}
      <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 5, gap: 2 }}>
        <div style={{
          width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
          background: isSuccess ? 'var(--accent)' : isError ? 'var(--error)' : color,
          boxShadow: isSuccess ? '0 0 8px var(--accent)' : undefined,
        }} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 2 }}>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: '1px 5px',
            background: `${color}18`, color, border: `1px solid ${color}30`,
            borderRadius: 'var(--radius-sm)', letterSpacing: '0.08em', flexShrink: 0,
          }}>
            {prefix}
          </span>
          {event.agent_name && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', flexShrink: 0 }}>
              [{event.agent_name}]
            </span>
          )}
        </div>
        <p style={{
          fontSize: 12, color: isSuccess ? 'var(--accent)' : isError ? 'var(--error)' : 'var(--text-primary)',
          lineHeight: 1.5, wordBreak: 'break-word',
        }}>
          {event.message}
        </p>
      </div>
    </div>
  );
}

export default function ExecutionTimeline({ events, status }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [events.length]);

  if (events.length === 0 && status === 'idle') return null;

  return (
    <div style={{
      background: 'var(--bg-base)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius-lg)',
      overflow: 'hidden',
    }}>
      {/* Terminal header bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
        padding: 'var(--space-2) var(--space-4)',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-surface)',
      }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--error)' }} />
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--warning)' }} />
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--success)' }} />
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'var(--space-2)', letterSpacing: '0.05em' }}>
          EXECUTION LOG
        </span>
        {status === 'running' && (
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
            <div className="spinner" />
            <span style={{ fontSize: 10, color: 'var(--warning)' }}>RUNNING</span>
          </div>
        )}
        {status === 'done' && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--accent)', letterSpacing: '0.05em' }}>
            ✓ COMPLETE
          </span>
        )}
        {status === 'failed' && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--error)' }}>✗ FAILED</span>
        )}
      </div>

      {/* Log content */}
      <div style={{
        padding: 'var(--space-2) var(--space-4)',
        maxHeight: 360, overflowY: 'auto',
        fontFamily: 'var(--font)',
      }}>
        {events.length === 0 ? (
          <div style={{ padding: 'var(--space-4) 0', color: 'var(--text-muted)', fontSize: 11 }}>
            <span style={{ animation: 'blink 1s step-end infinite' }}>▊</span> 等待执行...
          </div>
        ) : (
          events.map((e, i) => <LogLine key={e.sequence} event={e} index={i} />)
        )}
        {status === 'running' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 'var(--space-2) 0' }}>
            <div className="spinner" style={{ width: 10, height: 10 }} />
            <span style={{
              fontSize: 11, color: 'var(--text-muted)',
              animation: 'blink 1.2s step-end infinite',
            }}>
              处理中...
            </span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
```

---

## Task 5: FeishuAssetCard Component

**Files:**
- Rewrite: `frontend/src/components/FeishuAssetCard.tsx`

- [ ] **Step 1: Rewrite FeishuAssetCard.tsx**

```tsx
// frontend/src/components/FeishuAssetCard.tsx
import type { PublishedAsset } from '../services/types';

interface Props {
  asset: PublishedAsset;
}

const ASSET_META: Record<string, { label: string; color: string; icon: string }> = {
  doc:     { label: '飞书文档', color: 'var(--info)',    icon: '📄' },
  bitable: { label: '多维表格', color: 'var(--success)', icon: '📊' },
  message: { label: '群消息',   color: 'var(--warning)', icon: '💬' },
  task:    { label: '飞书任务', color: '#c084fc',        icon: '✓' },
  wiki:    { label: '知识库',   color: 'var(--gold)',    icon: '📚' },
};

export default function FeishuAssetCard({ asset }: Props) {
  const meta = ASSET_META[asset.type] || { label: asset.type, color: 'var(--text-secondary)', icon: '📎' };

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
      padding: 'var(--space-3) var(--space-4)',
      borderBottom: '1px solid var(--border)',
      animation: 'fade-in 0.2s ease both',
    }}>
      <span style={{
        fontSize: 13, flexShrink: 0,
        width: 28, textAlign: 'center',
      }}>
        {meta.icon}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <span style={{
            fontSize: 9, fontWeight: 700, padding: '1px 5px',
            background: `${meta.color}18`, color: meta.color,
            border: `1px solid ${meta.color}30`,
            borderRadius: 'var(--radius-sm)', letterSpacing: '0.08em',
          }}>
            {meta.label}
          </span>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-primary)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {asset.title || asset.type}
        </p>
      </div>

      {asset.url && (
        <a
          href={asset.url}
          target="_blank"
          rel="noopener noreferrer"
          className="btn btn-sm"
          style={{ flexShrink: 0, textDecoration: 'none' }}
        >
          打开 ↗
        </a>
      )}
    </div>
  );
}
```

---

## Task 6: Workbench Page

**Files:**
- Rewrite: `frontend/src/pages/Workbench.tsx`

- [ ] **Step 1: Rewrite Workbench.tsx**

```tsx
// frontend/src/pages/Workbench.tsx
import { useState, useEffect, useRef } from 'react';
import {
  submitTask, confirmTask, listAgents, createSSEConnection, getTaskStatus,
} from '../services/api';
import type { AgentInfo, SSEEvent, TaskPlanResponse } from '../services/types';
import ModuleCard from '../components/ModuleCard';
import ExecutionTimeline from '../components/ExecutionTimeline';
import { useNavigate } from 'react-router-dom';

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
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>('input');
  const [plan, setPlan] = useState<TaskPlanResponse | null>(null);
  const [selectedModules, setSelectedModules] = useState<string[]>([]);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { listAgents().then(setAgents).catch(console.error); }, []);

  const toggleModule = (id: string) => {
    setSelectedModules((prev) =>
      prev.includes(id) ? prev.filter((m) => m !== id) : [...prev, id]
    );
  };

  const handleSubmit = async () => {
    if (!inputText.trim() && !file) {
      setError('请输入任务描述或上传文件');
      return;
    }
    setError(null);
    setLoading(true);
    setStep('planning');
    try {
      const result = await submitTask(inputText, file ?? undefined);
      setPlan(result);
      setTaskId(result.task_id);
      setSelectedModules(result.selected_modules);
      setStep('confirm');
    } catch {
      setError('任务识别失败，请重试');
      setStep('input');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!taskId || selectedModules.length === 0) {
      setError('请至少选择一个分析模块');
      return;
    }
    setError(null);
    setLoading(true);
    setStep('running');
    setEvents([]);
    try {
      await confirmTask(taskId, selectedModules);
      const es = createSSEConnection(taskId);
      es.onmessage = (e) => {
        const data = JSON.parse(e.data) as SSEEvent & { status?: string };
        if (data.event_type === 'stream.end') {
          es.close();
          setStep('done');
          setLoading(false);
        } else if (data.event_type !== 'stream.timeout') {
          setEvents((prev) => [...prev, data as SSEEvent]);
        }
      };
      es.onerror = async () => {
        es.close();
        if (taskId) {
          try {
            const statusData = await getTaskStatus(taskId);
            const s = (statusData as { status: string }).status;
            if (s === 'done') { setStep('done'); }
            else if (s === 'failed') { setStep('confirm'); setError('任务执行失败，请重新确认执行'); }
            else { setError('连接中断，请刷新页面查看进度'); }
          } catch {
            setStep('confirm');
            setError('连接中断，请刷新页面');
          }
        }
        setLoading(false);
      };
    } catch {
      setError('执行失败');
      setStep('confirm');
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'var(--space-8) var(--space-6)' }}>

      {/* Header */}
      <div style={{ marginBottom: 'var(--space-10)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' }}>
          <span style={{
            fontSize: 9, fontWeight: 700, letterSpacing: '0.15em', color: 'var(--accent)',
            textTransform: 'uppercase',
          }}>
            ◆ MISSION CONTROL
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>v1.0</span>
        </div>
        <h1 style={{
          fontSize: 28, fontWeight: 700, color: 'var(--text-primary)',
          letterSpacing: '-0.03em', lineHeight: 1.2, marginBottom: 8,
        }}>
          飞书 AI 工作台
        </h1>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          描述你的任务 → AI 自动识别类型 → 调用分析模块 → 结果同步飞书
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          marginBottom: 'var(--space-4)',
          padding: 'var(--space-3) var(--space-4)',
          background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)',
          borderRadius: 'var(--radius)',
          fontSize: 12, color: 'var(--error)',
          display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
        }}>
          <span>✗</span> {error}
          <button
            className="btn btn-ghost btn-sm"
            style={{ marginLeft: 'auto', color: 'var(--error)', padding: '2px 6px', fontSize: 10 }}
            onClick={() => setError(null)}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── STEP 01: Input ── */}
      <section style={{
        marginBottom: 'var(--space-4)',
        opacity: step === 'input' || step === 'planning' ? 1 : 0.6,
        transition: 'opacity 0.3s',
      }}>
        <div className="card" style={{ padding: 'var(--space-5)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '3px 8px',
              background: step === 'input' || step === 'planning' ? 'var(--accent-dim)' : 'var(--bg-elevated)',
              color: step === 'input' || step === 'planning' ? 'var(--accent)' : 'var(--text-muted)',
              border: `1px solid ${step === 'input' || step === 'planning' ? 'rgba(163,255,0,0.25)' : 'var(--border)'}`,
              borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
            }}>
              01
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>描述任务</span>
          </div>

          <textarea
            rows={4}
            className="input"
            placeholder="例如：分析本月经营数据，重点看收入趋势和成本风险..."
            value={inputText}
            disabled={step !== 'input'}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && step === 'input') handleSubmit();
            }}
            style={{ marginBottom: 'var(--space-3)', minHeight: 100 }}
          />

          {/* File upload */}
          <div
            style={{
              padding: 'var(--space-4)',
              border: `1px dashed ${file ? 'rgba(163,255,0,0.4)' : 'var(--border)'}`,
              borderRadius: 'var(--radius)',
              background: file ? 'var(--accent-dim)' : 'transparent',
              cursor: step !== 'input' ? 'not-allowed' : 'pointer',
              textAlign: 'center',
              transition: 'all 0.15s',
              marginBottom: 'var(--space-4)',
            }}
            onClick={() => step === 'input' && fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); }}
            onDrop={(e) => {
              e.preventDefault();
              if (step !== 'input') return;
              const dropped = e.dataTransfer.files[0];
              if (dropped && (dropped.name.endsWith('.csv') || dropped.name.endsWith('.txt'))) {
                setFile(dropped);
              }
            }}
          >
            {file ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <span style={{ fontSize: 12, color: 'var(--accent)' }}>📎 {file.name}</span>
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ color: 'var(--text-muted)', padding: '1px 4px', fontSize: 10 }}
                  onClick={(e) => { e.stopPropagation(); setFile(null); }}
                >✕</button>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  拖拽或点击上传数据文件
                </p>
                <p style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>CSV · TXT</p>
              </div>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.txt"
            style={{ display: 'none' }}
            onChange={(e) => { if (e.target.files?.[0]) setFile(e.target.files[0]); }}
          />

          <button
            className={`btn btn-accent btn-lg btn-block`}
            disabled={step !== 'input' || loading}
            onClick={handleSubmit}
          >
            {loading && step === 'planning' ? (
              <><div className="spinner" style={{ borderTopColor: '#000', borderColor: 'rgba(0,0,0,0.2)' }} /> 识别中...</>
            ) : (
              <>⚡ 识别任务 <span style={{ opacity: 0.6, fontSize: 10 }}>⌘↵</span></>
            )}
          </button>
        </div>
      </section>

      {/* ── STEP 02: Confirm modules ── */}
      {(step === 'confirm' || step === 'running' || step === 'done') && plan && (
        <section style={{ marginBottom: 'var(--space-4)', animation: 'fade-in-up 0.25s ease both' }}>
          <div className="card" style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '3px 8px',
                background: step === 'confirm' ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                color: step === 'confirm' ? 'var(--accent)' : 'var(--text-muted)',
                border: `1px solid ${step === 'confirm' ? 'rgba(163,255,0,0.25)' : 'var(--border)'}`,
                borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
              }}>
                02
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>选择分析模块</span>
              <span style={{
                marginLeft: 'auto', fontSize: 9, fontWeight: 700, padding: '2px 8px',
                background: 'rgba(129,140,248,0.12)', color: 'var(--info)',
                border: '1px solid rgba(129,140,248,0.2)',
                borderRadius: 'var(--radius-sm)', letterSpacing: '0.08em',
              }}>
                {plan.task_type_label}
              </span>
            </div>

            {/* Reasoning */}
            <p style={{
              fontSize: 11, color: 'var(--text-secondary)', padding: 'var(--space-3) var(--space-4)',
              background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
              marginBottom: 'var(--space-4)', lineHeight: 1.6,
            }}>
              <span style={{ color: 'var(--text-muted)' }}>REASON /</span>{' '}{plan.reasoning}
            </p>

            {/* Preset combos */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap', marginBottom: 'var(--space-4)' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>PRESET</span>
              {PRESET_COMBOS.map((c) => (
                <button
                  key={c.label}
                  className="btn btn-sm"
                  disabled={step !== 'confirm'}
                  onClick={() => setSelectedModules(c.modules)}
                  style={{
                    borderColor: JSON.stringify(selectedModules.sort()) === JSON.stringify([...c.modules].sort())
                      ? 'var(--accent)' : undefined,
                    color: JSON.stringify(selectedModules.sort()) === JSON.stringify([...c.modules].sort())
                      ? 'var(--accent)' : undefined,
                  }}
                >
                  {c.label}
                </button>
              ))}
            </div>

            {/* Agent grid */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 'var(--space-3)',
              marginBottom: 'var(--space-4)',
            }}>
              {agents.map((agent) => (
                <ModuleCard
                  key={agent.id}
                  agent={agent}
                  selected={selectedModules.includes(agent.id)}
                  onToggle={step === 'confirm' ? toggleModule : () => {}}
                  disabled={step !== 'confirm'}
                />
              ))}
            </div>

            <button
              className="btn btn-accent btn-lg btn-block"
              disabled={step !== 'confirm' || selectedModules.length === 0 || loading}
              onClick={handleConfirm}
            >
              {loading && step === 'running' ? (
                <><div className="spinner" style={{ borderTopColor: '#000', borderColor: 'rgba(0,0,0,0.2)' }} /> 执行中...</>
              ) : (
                <>▶ 确认执行 <span style={{ opacity: 0.7 }}>{selectedModules.length} 个模块</span></>
              )}
            </button>
          </div>
        </section>
      )}

      {/* ── STEP 03: Execution ── */}
      {(step === 'running' || step === 'done') && (
        <section style={{ marginBottom: 'var(--space-4)', animation: 'fade-in-up 0.25s ease both' }}>
          <div className="card" style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-4)' }}>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '3px 8px',
                background: step === 'done' ? 'rgba(52,211,153,0.12)' : 'rgba(251,146,60,0.12)',
                color: step === 'done' ? 'var(--success)' : 'var(--warning)',
                border: `1px solid ${step === 'done' ? 'rgba(52,211,153,0.25)' : 'rgba(251,146,60,0.25)'}`,
                borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
              }}>
                03
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>执行日志</span>
              {step === 'running' && (
                <div style={{
                  marginLeft: 'auto',
                  width: 120, height: 2,
                  background: 'var(--bg-elevated)',
                  borderRadius: 1, overflow: 'hidden',
                }}>
                  <div style={{
                    height: '100%',
                    background: 'linear-gradient(90deg, var(--accent), transparent)',
                    animation: 'progress-fill 3s ease-out infinite',
                    transformOrigin: 'left',
                  }} />
                </div>
              )}
            </div>

            <ExecutionTimeline events={events} status={step === 'running' ? 'running' : 'done'} />

            {step === 'done' && taskId && (
              <button
                className="btn btn-accent btn-lg"
                style={{ marginTop: 'var(--space-4)' }}
                onClick={() => navigate(`/results/${taskId}`)}
              >
                查看完整报告 →
              </button>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
```

---

## Task 7: ResultView Page

**Files:**
- Rewrite: `frontend/src/pages/ResultView.tsx`

- [ ] **Step 1: Rewrite ResultView.tsx**

```tsx
// frontend/src/pages/ResultView.tsx
import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getTaskResults, publishTask } from '../services/api';
import type { TaskResultsResponse } from '../services/types';
import FeishuAssetCard from '../components/FeishuAssetCard';

const STATUS_META: Record<string, { label: string; color: string }> = {
  done:     { label: 'DONE',     color: 'var(--success)' },
  running:  { label: 'RUNNING',  color: 'var(--warning)' },
  failed:   { label: 'FAILED',   color: 'var(--error)'   },
  pending:  { label: 'PENDING',  color: 'var(--text-muted)' },
};

const PUBLISH_OPTIONS = [
  { value: 'doc',     label: '飞书文档',   desc: '完整分析报告' },
  { value: 'bitable', label: '多维表格',   desc: '行动建议清单' },
  { value: 'message', label: '群消息',     desc: '管理摘要推送' },
  { value: 'task',    label: '飞书任务',   desc: '行动项转任务' },
];

export default function ResultView() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<TaskResultsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);
  const [showPublish, setShowPublish] = useState(false);
  const [publishTypes, setPublishTypes] = useState<string[]>(['doc', 'task']);
  const [docTitle, setDocTitle] = useState('');
  const [chatId, setChatId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) return;
    getTaskResults(taskId)
      .then((d) => { setData(d); if (d.agent_results[0]) setExpandedAgent(d.agent_results[0].agent_id); })
      .catch(() => setError('加载结果失败'))
      .finally(() => setLoading(false));
  }, [taskId]);

  const handlePublish = async () => {
    if (!taskId) return;
    setPublishing(true);
    setError(null);
    try {
      await publishTask(taskId, publishTypes, {
        docTitle: docTitle || undefined,
        chatId: chatId || undefined,
      });
      const updated = await getTaskResults(taskId);
      setData(updated);
      setShowPublish(false);
    } catch {
      setError('发布失败，请检查飞书配置');
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 300, gap: 12 }}>
        <div className="spinner" />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>加载报告...</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div style={{ padding: 'var(--space-8) var(--space-6)', maxWidth: 860, margin: '0 auto' }}>
        <p style={{ fontSize: 13, color: 'var(--error)' }}>任务不存在</p>
        <button className="btn" style={{ marginTop: 'var(--space-4)' }} onClick={() => navigate('/')}>← 返回工作台</button>
      </div>
    );
  }

  const statusMeta = STATUS_META[data.status] || { label: data.status.toUpperCase(), color: 'var(--text-muted)' };

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'var(--space-8) var(--space-6)' }}>

      {/* Back + header */}
      <div style={{ marginBottom: 'var(--space-8)' }}>
        <button
          className="btn btn-ghost btn-sm"
          style={{ marginBottom: 'var(--space-4)', color: 'var(--text-muted)' }}
          onClick={() => navigate('/')}
        >
          ← 返回工作台
        </button>

        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.03em', marginBottom: 6 }}>
              {data.task_type_label}报告
            </h1>
            <p style={{ fontSize: 11, color: 'var(--text-muted)' }}>TASK / {taskId}</p>
          </div>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '4px 10px',
            background: `${statusMeta.color}18`, color: statusMeta.color,
            border: `1px solid ${statusMeta.color}30`,
            borderRadius: 'var(--radius-sm)', letterSpacing: '0.1em',
            alignSelf: 'flex-start',
          }}>
            {statusMeta.label}
          </span>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div style={{
          marginBottom: 'var(--space-4)', padding: 'var(--space-3) var(--space-4)',
          background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)',
          borderRadius: 'var(--radius)', fontSize: 12, color: 'var(--error)',
        }}>
          ✗ {error}
        </div>
      )}

      {/* Summary card */}
      {data.result_summary && (
        <div
          className="card"
          style={{
            padding: 'var(--space-5)', marginBottom: 'var(--space-4)',
            borderColor: 'rgba(163,255,0,0.15)',
            background: 'rgba(163,255,0,0.04)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--space-3)' }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.15em' }}>◆ EXECUTIVE SUMMARY</span>
          </div>
          <p style={{ fontSize: 13, color: 'var(--text-primary)', lineHeight: 1.7 }}>
            {data.result_summary}
          </p>
        </div>
      )}

      {/* Agent results accordion */}
      <div style={{ marginBottom: 'var(--space-4)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.15em', marginBottom: 'var(--space-3)', textTransform: 'uppercase' }}>
          分析模块报告 ({data.agent_results.length})
        </div>

        {data.agent_results.map((r, ri) => {
          const expanded = expandedAgent === r.agent_id;
          return (
            <div
              key={r.agent_id}
              className="card"
              style={{
                marginBottom: 'var(--space-2)',
                overflow: 'hidden',
                borderColor: expanded ? 'var(--border-bright)' : 'var(--border)',
                animation: `fade-in-up 0.2s ease both`,
                animationDelay: `${ri * 60}ms`,
              }}
            >
              {/* Accordion header */}
              <button
                style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                  padding: 'var(--space-4) var(--space-5)',
                  background: 'none', border: 'none', cursor: 'pointer',
                  textAlign: 'left',
                  borderBottom: expanded ? '1px solid var(--border)' : 'none',
                }}
                onClick={() => setExpandedAgent(expanded ? null : r.agent_id)}
              >
                <span style={{
                  fontSize: 9, fontWeight: 700, padding: '2px 6px',
                  background: 'var(--bg-elevated)', color: 'var(--text-secondary)',
                  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                  letterSpacing: '0.08em', flexShrink: 0,
                }}>
                  {r.agent_name}
                </span>
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', flex: 1 }}>
                  {r.sections.length} 个分析板块
                  {r.action_items.length > 0 && ` · ${r.action_items.length} 项行动建议`}
                </span>
                <span style={{
                  fontSize: 11, color: 'var(--text-muted)',
                  transform: expanded ? 'rotate(180deg)' : 'none',
                  transition: 'transform 0.2s',
                }}>▼</span>
              </button>

              {/* Accordion content */}
              {expanded && (
                <div style={{ padding: 'var(--space-5)' }}>
                  {r.sections.map((s, i) => (
                    <div key={i} style={{ marginBottom: 'var(--space-5)' }}>
                      <div style={{
                        fontSize: 11, fontWeight: 700, color: 'var(--text-primary)',
                        marginBottom: 'var(--space-2)', paddingBottom: 'var(--space-2)',
                        borderBottom: '1px solid var(--border)',
                      }}>
                        {s.title}
                      </div>
                      <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.8, whiteSpace: 'pre-line' }}>
                        {s.content}
                      </p>
                    </div>
                  ))}

                  {r.action_items.length > 0 && (
                    <div>
                      <div style={{
                        fontSize: 10, fontWeight: 700, color: 'var(--accent)',
                        letterSpacing: '0.1em', marginBottom: 'var(--space-3)',
                      }}>
                        ACTION ITEMS
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                        {r.action_items.map((item, i) => (
                          <div key={i} style={{
                            display: 'flex', alignItems: 'flex-start', gap: 'var(--space-3)',
                            fontSize: 12, color: 'var(--text-primary)',
                          }}>
                            <span style={{
                              flexShrink: 0, width: 18, height: 18,
                              border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                              fontSize: 9, color: 'var(--text-muted)', fontWeight: 700, marginTop: 2,
                            }}>
                              {String(i + 1).padStart(2, '0')}
                            </span>
                            <span style={{ lineHeight: 1.6 }}>{item}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Published assets */}
      {data.published_assets.length > 0 && (
        <div className="card" style={{ marginBottom: 'var(--space-4)', overflow: 'hidden' }}>
          <div style={{
            padding: 'var(--space-3) var(--space-4)',
            borderBottom: '1px solid var(--border)',
            fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.15em',
          }}>
            已同步到飞书
          </div>
          {data.published_assets.map((asset, i) => (
            <FeishuAssetCard key={i} asset={asset} />
          ))}
        </div>
      )}

      {/* Publish to Feishu */}
      {data.status === 'done' && (
        <div style={{ marginBottom: 'var(--space-4)' }}>
          {!showPublish ? (
            <button className="btn btn-accent btn-lg btn-block" onClick={() => setShowPublish(true)}>
              ↗ 同步到飞书
            </button>
          ) : (
            <div className="card" style={{ padding: 'var(--space-5)' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.15em', marginBottom: 'var(--space-4)' }}>
                选择同步内容
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
                {PUBLISH_OPTIONS.map((opt) => {
                  const checked = publishTypes.includes(opt.value);
                  return (
                    <div
                      key={opt.value}
                      role="checkbox"
                      aria-checked={checked}
                      onClick={() => setPublishTypes((prev) =>
                        prev.includes(opt.value) ? prev.filter((v) => v !== opt.value) : [...prev, opt.value]
                      )}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 'var(--space-3)',
                        padding: 'var(--space-3) var(--space-4)',
                        background: checked ? 'var(--accent-dim)' : 'var(--bg-elevated)',
                        border: `1px solid ${checked ? 'rgba(163,255,0,0.25)' : 'var(--border)'}`,
                        borderRadius: 'var(--radius)', cursor: 'pointer',
                        transition: 'all 0.15s',
                      }}
                    >
                      <div style={{
                        width: 14, height: 14, flexShrink: 0,
                        border: `1.5px solid ${checked ? 'var(--accent)' : 'var(--border-bright)'}`,
                        borderRadius: 'var(--radius-sm)', background: checked ? 'var(--accent)' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {checked && <svg width="8" height="6" viewBox="0 0 8 6" fill="none"><path d="M1 3L3 5L7 1" stroke="#000" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                      </div>
                      <div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: checked ? 'var(--accent)' : 'var(--text-primary)' }}>{opt.label}</div>
                        <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{opt.desc}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              <input
                className="input"
                placeholder="文档标题（可选）"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                style={{ marginBottom: 'var(--space-2)' }}
              />
              <input
                className="input"
                placeholder="群 ID（可选，默认使用配置的群）"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                style={{ marginBottom: 'var(--space-4)' }}
              />

              <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
                <button
                  className="btn btn-accent btn-lg"
                  style={{ flex: 1, justifyContent: 'center' }}
                  disabled={publishing || publishTypes.length === 0}
                  onClick={handlePublish}
                >
                  {publishing ? <><div className="spinner" style={{ borderTopColor: '#000', borderColor: 'rgba(0,0,0,0.2)' }} />同步中...</> : '↗ 确认同步'}
                </button>
                <button
                  className="btn"
                  onClick={() => setShowPublish(false)}
                  disabled={publishing}
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

---

## Task 8: History Page

**Files:**
- Rewrite: `frontend/src/pages/History.tsx`

- [ ] **Step 1: Rewrite History.tsx**

```tsx
// frontend/src/pages/History.tsx
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listTasks } from '../services/api';
import type { TaskListItem } from '../services/types';

const STATUS_META: Record<string, { label: string; color: string }> = {
  done:     { label: 'DONE',     color: 'var(--success)' },
  running:  { label: 'RUNNING',  color: 'var(--warning)' },
  failed:   { label: 'FAILED',   color: 'var(--error)'   },
  pending:  { label: 'PENDING',  color: 'var(--text-muted)' },
  planning: { label: 'PLANNING', color: 'var(--info)'    },
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export default function History() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listTasks()
      .then(setTasks)
      .catch(() => setError('加载历史记录失败'))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: 'var(--space-8) var(--space-6)' }}>

      {/* Header */}
      <div style={{ marginBottom: 'var(--space-8)' }}>
        <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.15em', color: 'var(--accent)', marginBottom: 'var(--space-2)' }}>
          ◆ MISSION HISTORY
        </div>
        <h1 style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.03em' }}>历史任务</h1>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 'var(--space-4) 0' }}>
          <div className="spinner" />
          <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>加载中...</span>
        </div>
      )}

      {/* Error */}
      {error && (
        <div style={{
          padding: 'var(--space-3) var(--space-4)',
          background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.2)',
          borderRadius: 'var(--radius)', fontSize: 12, color: 'var(--error)',
          marginBottom: 'var(--space-4)',
        }}>
          ✗ {error}
        </div>
      )}

      {/* Table header */}
      {!loading && tasks.length > 0 && (
        <div style={{
          display: 'grid', gridTemplateColumns: '80px 1fr 100px 80px',
          gap: 'var(--space-4)', padding: 'var(--space-2) var(--space-4)',
          marginBottom: 'var(--space-1)',
        }}>
          {['STATUS', '任务描述', '时间', ''].map((h) => (
            <span key={h} style={{ fontSize: 9, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.1em' }}>{h}</span>
          ))}
        </div>
      )}

      {/* Task rows */}
      {!loading && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          {tasks.length === 0 ? (
            <div style={{ padding: 'var(--space-12) var(--space-4)', textAlign: 'center' }}>
              <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>暂无历史任务</p>
              <button className="btn btn-accent" style={{ marginTop: 'var(--space-4)' }} onClick={() => navigate('/')}>
                创建首个任务
              </button>
            </div>
          ) : (
            tasks.map((task, i) => {
              const meta = STATUS_META[task.status] || { label: task.status.toUpperCase(), color: 'var(--text-muted)' };
              const canView = task.status !== 'planning' && task.status !== 'pending';

              return (
                <div
                  key={task.id}
                  className="card"
                  style={{
                    display: 'grid', gridTemplateColumns: '80px 1fr 100px 80px',
                    gap: 'var(--space-4)', padding: 'var(--space-3) var(--space-4)',
                    alignItems: 'center',
                    animation: `fade-in-up 0.2s ease both`,
                    animationDelay: `${Math.min(i * 40, 300)}ms`,
                    cursor: canView ? 'pointer' : 'default',
                    transition: 'border-color 0.15s, background 0.15s',
                  }}
                  onClick={() => canView && navigate(`/results/${task.id}`)}
                  onMouseEnter={(e) => {
                    if (canView) {
                      (e.currentTarget as HTMLElement).style.borderColor = 'var(--border-bright)';
                      (e.currentTarget as HTMLElement).style.background = 'var(--bg-elevated)';
                    }
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.borderColor = '';
                    (e.currentTarget as HTMLElement).style.background = '';
                  }}
                >
                  {/* Status */}
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: '2px 6px',
                    background: `${meta.color}18`, color: meta.color,
                    border: `1px solid ${meta.color}30`,
                    borderRadius: 'var(--radius-sm)', letterSpacing: '0.08em',
                    display: 'inline-block',
                    ...(task.status === 'running' ? { animation: 'glow-pulse 2s ease-in-out infinite' } : {}),
                  }}>
                    {meta.label}
                  </span>

                  {/* Description */}
                  <div>
                    {task.task_type_label && (
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '1px 5px', marginRight: 8,
                        background: 'rgba(129,140,248,0.12)', color: 'var(--info)',
                        border: '1px solid rgba(129,140,248,0.2)',
                        borderRadius: 'var(--radius-sm)', letterSpacing: '0.06em',
                      }}>
                        {task.task_type_label}
                      </span>
                    )}
                    <span style={{
                      fontSize: 12, color: 'var(--text-secondary)',
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline',
                    }}>
                      {task.input_text || '（文件上传）'}
                    </span>
                  </div>

                  {/* Time */}
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {formatDate(task.created_at)}
                  </span>

                  {/* Action */}
                  <div>
                    {canView && (
                      <span style={{ fontSize: 11, color: 'var(--accent)' }}>查看 →</span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
```

---

## Task 9: Final Verification

- [ ] **Step 1: TypeScript compile check**

```bash
cd /Users/jassionyang/multiagent-lark/frontend && npx tsc --noEmit 2>&1
```

Expected: No errors (zero output). Fix any type errors before proceeding.

- [ ] **Step 2: Check no Ant Design imports remain in modified files**

```bash
grep -r "from 'antd'" /Users/jassionyang/multiagent-lark/frontend/src/ | grep -v node_modules
grep -r "from '@ant-design" /Users/jassionyang/multiagent-lark/frontend/src/ | grep -v node_modules
```

Expected: Zero matches.

- [ ] **Step 3: Check services are untouched**

```bash
diff /Users/jassionyang/multiagent-lark/frontend/src/services/api.ts /dev/stdin << 'EOF'
EOF
```

Actually just verify `api.ts` and `types.ts` haven't been modified — they should contain only `axios` and type definitions, no UI imports.

- [ ] **Step 4: Start dev server and visually verify**

```bash
cd /Users/jassionyang/multiagent-lark/frontend && npm run dev
```

Open http://localhost:5173 and verify:
- Dark background (#050508) with dot grid pattern
- JetBrains Mono font loaded
- Electric lime (#a3ff00) accent on CTA buttons
- Navigation bar with "AI" badge and "ONLINE" status dot
- Workbench has 3 numbered steps: 01 / 02 / 03
- No Ant Design blue/white default styling visible

- [ ] **Step 5: Remove App.css if it exists and is now unused**

```bash
cd /Users/jassionyang/multiagent-lark/frontend && grep -r "App.css" src/ && echo "Referenced" || echo "Safe to remove"
```

If not referenced: `rm /Users/jassionyang/multiagent-lark/frontend/src/App.css`

---

## Self-Review

**Spec coverage:**
- ✅ All 3 pages redesigned: Workbench, ResultView, History
- ✅ All 3 components redesigned: ExecutionTimeline, ModuleCard, FeishuAssetCard
- ✅ Design system in index.css (colors, fonts, animations, shared primitives)
- ✅ App shell (Nav) redesigned
- ✅ index.html updated with JetBrains Mono
- ✅ services/api.ts and types.ts NOT touched
- ✅ All functionality preserved (SSE, file upload, publish modal)

**Placeholder scan:** None — all code is complete and specific.

**Type consistency:**
- `AgentInfo`, `SSEEvent`, `TaskPlanResponse`, `TaskResultsResponse`, `TaskListItem`, `PublishedAsset` — all imported from `../services/types` unchanged
- `ModuleCard` props: `{ agent, selected, onToggle, disabled? }` consistent
- `ExecutionTimeline` props: `{ events: SSEEvent[], status: 'running' | 'done' | 'failed' | 'idle' }` consistent
- `FeishuAssetCard` props: `{ asset: PublishedAsset }` consistent
