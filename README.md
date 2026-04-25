# Puff C21 多 Agent 协同决策工作台

> 飞书 AI 挑战赛参赛项目 · AI 产品赛道

<img width="1000" height="400" alt="产品封面" src="https://github.com/user-attachments/assets/80faa5a3-23f4-4916-b008-c6dfec4d1006" />

**Puff! Complex to One — 做你的个人协作团队**

基于飞书生态的轻量化多 Agent 协作工具：用户描述任务，AI 自动识别类型、调用多 Agent 模块协同分析、结果实时同步飞书，一键完成流程搭建与任务闭环。

---

## 目录

- [产品定位](#产品定位)
- [核心功能](#核心功能)
- [多 Agent 协同](#多-agent-协同)
- [内容运营虚拟组织](#内容运营虚拟组织)
- [技术架构](#技术架构)
- [快速开始](#快速开始)
- [环境变量说明](#环境变量说明)
- [API 参考](#api-参考)
- [飞书应用权限](#飞书应用权限)
- [支持的 LLM 服务商](#支持的-llm-服务商)
- [国际版 Lark 支持](#国际版-lark-支持)
- [变更日志](#变更日志)

---

## 产品定位

当前飞书 CLI/Agent 能力停留在通用性执行——用户给指令，系统执行单一任务，用户仍需自己判断任务类型、应调用哪些工具。

**本产品填补这个缺口**：为企业在经营分析、立项评估、风险分析、内容规划等复杂任务上提供一站式 AI 协作入口。

- **差异化定位**：区别于飞书现有 AI 仅支持整理消息、添加日历等单一通用型任务，本产品面向复杂协作任务，自动调度多角色 Agent 协同完成。
- **飞书生态深度融合**：读取飞书文档/表格/任务/日历，分析结果一键发布为飞书文档、多维表格、群消息或任务卡片。

---

## 核心功能

### 主工作流：多 Agent 协同分析

```
① 用户描述任务（文字 / 上传文件）
② AI 自动识别任务类型，推荐分析模块组合
③ 用户确认 / 调整模块组合（或手动指定）
④ 多 Agent 依赖感知波次执行，CEO 助理最后汇总
⑤ 结果同步到飞书（文档 / 多维表格 / 演示文稿 / 群消息 / 任务）
```

### 七岗多智能体 · 多维表格自驱工作流

```
① 用户在分析任务表写入任务（可选粘贴 CSV 数据源）
② 调度器领取 → Wave1 五岗并行分析（数据/内容/SEO/产品/运营）
③ Wave2 财务顾问基于数据分析师输出继续深挖
④ Wave3 CEO 助理汇总全部上游，输出决策摘要 + A/B 选项
⑤ 七岗输出写回多维表格：🟢🟡🔴 健康度 / ⭐ 置信度 / 🔥 紧急度 / 进度条
⑥ 前端 SSE 实时推送 Wave 进度；CEO 行动项同步到飞书原生 Tasks
⑦ 行动项生成新的「待分析」任务 → 系统自驱闭环
```

---

## 多 Agent 协同

### Agent 模块

| 模块 ID | 中文名 | 职责 | 执行顺序 |
|---------|--------|------|----------|
| `data_analyst` | 数据分析师 | 数据趋势、异常、核心指标洞察 | 第一波（无依赖） |
| `finance_advisor` | 财务顾问 | 收支结构、现金流、财务风险 | 第二波（依赖 `data_analyst`） |
| `seo_advisor` | SEO/增长顾问 | 流量结构、关键词机会、内容增长 | 第一波（无依赖） |
| `content_manager` | 内容负责人 | 文档写作、知识库整理、内容归档 | 第一波（无依赖） |
| `product_manager` | 产品经理 | 需求分析、PRD、产品路线图 | 第一波（无依赖） |
| `operations_manager` | 运营负责人 | 行动拆解、任务分配、执行跟进 | 第一波（无依赖） |
| `ceo_assistant` | CEO 助理 | 汇总所有结论，生成管理决策摘要 | 最后波（依赖所有上游） |

> 依赖关系由 `registry.py::AGENT_DEPENDENCIES` DAG 拓扑排序决定。`finance_advisor` 在 `data_analyst` 完成后启动；`ceo_assistant` 始终最后执行，接收所有上游输出。

### 任务类型

AI 自动从以下 9 种类型识别并推荐 Agent 组合：

| 任务类型 | 中文名 | 默认 Agent 组合 |
|----------|--------|----------------|
| `business_analysis` | 经营分析 | data_analyst → finance_advisor → ceo_assistant |
| `project_evaluation` | 立项评估 | product_manager → finance_advisor → ceo_assistant |
| `content_growth` | 内容增长 | seo_advisor + content_manager + operations_manager |
| `risk_analysis` | 风险分析 | finance_advisor + operations_manager → ceo_assistant |
| `knowledge_organization` | 知识整理 | content_manager |
| `document_processing` | 文档处理 | content_manager |
| `calendar_analysis` | 日历整理 | data_analyst |
| `chat_organization` | 群聊整理 | content_manager |
| `general` | 综合分析 | data_analyst + operations_manager → ceo_assistant |

---

## 多维表格虚拟组织（七岗多智能体）

本模块实现「七岗 AI 数字员工」通过飞书多维表格协同工作，覆盖竞赛要求的全部四个核心能力模块。

### 完整业务链路（数据产生 → 再流转闭环）

```
写入种子任务
     │
     ▼
待分析 ──[调度器领取]──▶ 分析中
                              │
              ┌───────────────┴────────────────┐
              │      Wave 1（5个并行Agent）      │
              │  数据分析师 内容经理 SEO顾问      │
              │  产品经理   运营经理              │
              └──────────────┬─────────────────┘
                             │
              ┌──────────────┴──────────────────┐
              │   Wave 2（依赖数据分析师输出）     │
              │         财务顾问                 │
              └──────────────┬──────────────────┘
                             │
              ┌──────────────┴──────────────────┐
              │  Wave 3（汇总所有上游输出）        │
              │        CEO 助理                  │
              └──────────────┬──────────────────┘
                             │
             ┌───────────────┼────────────────────┐
             ▼               ▼                    ▼
        写入岗位分析表   写入综合报告表       飞书群消息通知
        （关联任务记录） （关联任务记录）
                             │
                             ▼
              CEO 行动项 → 自动生成新的「待分析」任务
                        （再流转，形成业务闭环）
                             │
                             ▼
                          已完成
```

### 四张多维表格（含表间关联字段）

| 表格 | 用途 | 关联关系 |
|------|------|----------|
| **分析任务** | 主表，驱动状态机 | 无（主表） |
| **岗位分析** | 每岗 Agent 的分析输出（6条/任务） | ←「关联任务」字段关联主表 |
| **综合报告** | CEO 助理综合决策报告 | ←「关联任务」字段关联主表 |
| **数字员工效能** | 各岗位处理任务数滚动统计 | 无 |

> 「关联任务」为飞书多维表格关联记录字段（type=18），实现跨表数据追溯与视图联动。

### 虚拟组织角色定义

| 角色（Agent） | 职责 | 依赖 |
|---------------|------|------|
| 数据分析师 | 指标拆解、趋势洞察、异常归因 | 无（Wave 1） |
| 内容负责人 | 内容资产盘点、创作策略 | 无（Wave 1） |
| SEO 顾问 | 关键词机会、流量增长路径 | 无（Wave 1） |
| 产品经理 | 需求分析、路线图规划 | 无（Wave 1） |
| 运营负责人 | 执行规划、任务拆解 | 无（Wave 1） |
| 财务顾问 | 收支诊断、现金流分析 | 数据分析师（Wave 2） |
| CEO 助理 | 跨职能整合、管理决策摘要 | 所有上游（Wave 3） |

### 工作流 REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/workflow/setup` | 一键创建多维表格结构（4 张表 + 6 个附加视图）+ 4 条种子任务 |
| `POST` | `/api/v1/workflow/start` | 启动后台调度循环 |
| `POST` | `/api/v1/workflow/stop` | 停止调度循环（立即生效） |
| `GET`  | `/api/v1/workflow/status` | 查看运行状态和表格信息 |
| `POST` | `/api/v1/workflow/seed` | 向分析任务表写入一条新的待处理任务 |
| `GET`  | `/api/v1/workflow/records` | 查询多维表格记录，支持 `?status=` 过滤 |
| `GET`  | `/api/v1/workflow/stream/{record_id}` | **SSE 实时进度流**（task.started / wave.completed / task.done / task.error） |

**典型使用流程：**

```bash
# 1. 初始化（创建三张表格 + 写入种子任务）
curl -X POST http://localhost:8000/api/v1/workflow/setup \
  -H "Content-Type: application/json" \
  -d '{"name": "内容运营虚拟组织"}'
# 返回 → {"app_token": "xxx", "url": "https://...", "table_ids": {"content": "tbl_A", ...}}

# 2. 启动循环（每 30s 轮询，每 5 轮生成周报）
curl -X POST http://localhost:8000/api/v1/workflow/start \
  -H "Content-Type: application/json" \
  -d '{
    "app_token": "xxx",
    "table_ids": {"content": "tbl_A", "performance": "tbl_B", "report": "tbl_C"},
    "interval": 30,
    "analysis_every": 5
  }'

# 3. 追加新任务
curl -X POST http://localhost:8000/api/v1/workflow/seed \
  -H "Content-Type: application/json" \
  -d '{"app_token": "xxx", "table_id": "tbl_A", "title": "大模型应用全景", "content_type": "行业洞察"}'

# 4. 手动触发分析
curl -X POST http://localhost:8000/api/v1/workflow/analyze \
  -H "Content-Type: application/json" \
  -d '{"app_token": "xxx", "content_table_id": "tbl_A", "report_table_id": "tbl_C"}'

# 5. 停止循环
curl -X POST http://localhost:8000/api/v1/workflow/stop

# 6. 查询已发布记录
curl "http://localhost:8000/api/v1/workflow/records?app_token=xxx&table_id=tbl_A&status=已发布"
```

### 注入真实数据源（让分析不再凭空估算）

直接在飞书多维表格的「数据源」字段粘贴 CSV / markdown / 纯文本，系统会自动识别类型并注入每个 agent：

```csv
指标,一月,二月,三月
MAU,85000,98000,112000
DAU,32000,38000,45000
付费转化率,2.1,2.4,2.8
30日留存,28,31,34
```

流水线日志会打印 `Data source parsed: type=csv rows=4 cols=4`，agent 输出将基于真实数字而非行业估算。

### 前端订阅实时进度流

```javascript
const es = new EventSource(`/api/v1/workflow/stream/${recordId}`);
es.addEventListener('task.started', e => console.log('开始:', JSON.parse(e.data)));
es.addEventListener('wave.completed', e => {
  const { payload } = JSON.parse(e.data);
  console.log(`Wave 进度 ${payload.progress * 100}%: ${payload.stage}`);
});
es.addEventListener('task.done', e => { console.log('完成!', JSON.parse(e.data)); es.close(); });
es.addEventListener('task.error', e => { console.log('失败:', JSON.parse(e.data)); es.close(); });
```

---

## 技术架构

```
frontend/   React 18 + TypeScript + Tailwind CSS + shadcn/ui + Vite
backend/    FastAPI + SQLite + asyncio + lark-oapi + httpx
```

### 后端核心模块

```
backend/app/
├── main.py               # FastAPI 入口，lifespan 管理（DB 初始化、OAuth token 恢复）
├── api/
│   ├── tasks.py          # 任务提交与确认执行
│   ├── events.py         # SSE 实时执行日志推送
│   ├── results.py        # 完整分析报告查询
│   ├── feishu.py         # 飞书数据读写（文档/日历/任务/群聊/发布）
│   ├── feishu_oauth.py   # 飞书 OAuth2 授权流程
│   ├── config.py         # 运行时配置变更（LLM、飞书凭证）
│   └── workflow.py       # 内容运营工作流管理 API（7 个端点）
├── agents/
│   ├── base_agent.py     # 基类：prompt 构建、LLM 调用、反思机制、输出解析
│   ├── registry.py       # 注册表 + AGENT_DEPENDENCIES DAG（拓扑排序决定执行波次）
│   └── [7 个 Agent 文件] # 各角色专属系统提示词 + 用户提示模板
├── bitable_workflow/
│   ├── schema.py           # 多维表格结构（28 种字段类型：SingleSelect/Rating/Progress/AutoNumber/CreatedTime/...）
│   ├── bitable_ops.py      # 多维表格记录 CRUD（直接 HTTP，with_retry 指数退避）
│   ├── workflow_agents.py  # 七岗 DAG 流水线（Wave1→Wave2→Wave3）+ 元数据/岗位/健康度/置信度映射
│   ├── scheduler.py        # 状态驱动调度（Phase 0 崩溃恢复 + Wave 进度广播）
│   ├── runner.py           # setup_workflow（创建表+视图+种子） / run_workflow_loop / stop_workflow
│   ├── agent_cache.py      # Redis 持久化 agent 结果（崩溃重试时跳过已完成 agent，可选）
│   └── progress_broker.py  # 进程内 SSE 事件 pub/sub（按 task_id 隔离订阅）
├── core/
│   ├── orchestrator.py   # 多 Agent 波次执行调度 + 重试
│   ├── task_planner.py   # LLM 任务路由（识别类型 + 推荐模块）
│   ├── llm_client.py     # LLM 调用工厂（openai_compatible / feishu_aily，含三次重试）
│   ├── event_emitter.py  # SSE 事件推送
│   └── data_parser.py    # 文件解析（CSV / TXT / MD）
└── feishu/
    ├── aily.py           # Feishu Aily AI 适配器（tenant token 缓存 + 轮询 + 指数退避）
    ├── bitable.py        # 多维表格 App/Table/Field 创建（lark-oapi SDK，with_retry）
    ├── doc.py            # 富文本文档发布（heading/callout/bullet/divider 结构化块）
    ├── im.py             # 即时消息发送
    ├── reader.py         # 飞书数据读取（优先 user_access_token）
    ├── publisher.py      # 统一发布入口（doc / bitable / slides / message）
    ├── retry.py          # 通用指数退避重试（token 过期自动刷新，4xx 快速失败）
    ├── slides.py         # 演示文稿发布（三层降级：lark-cli → Presentation API → 文档）
    └── user_token.py     # 用户 OAuth token 内存缓存
```

### 前端核心页面

```
frontend/src/
├── pages/
│   ├── Index.tsx              # 工作台主页（任务输入 + 模块选择 + 执行监控）
│   ├── ResultView.tsx         # 结果详情（分节报告 + 行动项 + 飞书发布）
│   ├── BitableWorkflow.tsx    # 七岗工作流仪表盘（初始化 / 启停 / SSE 实时进度）
│   ├── FeishuWorkspace.tsx    # 飞书工作区（云盘/日历/任务/群聊 四 Tab）
│   ├── Settings.tsx           # 设置页（LLM + 飞书配置 + OAuth 授权）
│   └── History.tsx            # 任务历史列表
├── services/
│   ├── api.ts                 # 主工作流任务 REST + SSE
│   ├── feishu.ts              # 飞书工作区数据读取
│   ├── workflow.ts            # 七岗工作流 + SSE 进度订阅（subscribeTaskProgress）
│   └── config.ts              # LLM/飞书配置读写
└── components/
    ├── ExecutionTimeline.tsx  # 执行日志（Agent 活动卡片 + 时间线）
    ├── ModuleCard.tsx         # Agent 选择卡片（含 persona 信息）
    ├── ContextSuggestions.tsx # 飞书上下文智能推荐
    └── FeishuAssetCard.tsx    # 发布资产卡片（doc/bitable/slides/message）
```

### 关键工程设计

| 问题 | 方案 |
|------|------|
| 多 Agent 依赖关系 | DAG 拓扑排序，Wave1（5并行）→ Wave2（财务）→ Wave3（CEO汇总） |
| 表间关联记录 | 岗位分析 / 综合报告表通过关联字段（type=18）与分析任务表关联，支持视图联动 |
| 业务闭环再流转 | CEO 行动项自动写回分析任务表（状态=待分析），系统持续自驱运行 |
| 飞书消息推送 | 任务完成后向配置群发送报告摘要卡片，非阻塞，未配置时静默跳过 |
| 调度循环重入防护 | `mark_starting()` 在请求处理函数内同步置 `_running=True`，后台任务启动前对外可见 |
| Bitable API 可靠性 | 全部 CRUD 套 `with_retry(max_attempts=3, base_delay=1s)` 指数退避 |
| 崩溃恢复 | Phase 0 每轮把遗留 ANALYZING 记录重置为待分析 |
| 效能统计 | 数字员工效能表滚动累计处理任务数，跨轮次持续累计 |
| Token 缓存 | tenant access token 提前 60s 刷新，避免在途请求过期 |
| 循环优雅停止 | `asyncio.wait_for(_stop_event.wait(), timeout=interval)` 立即响应 `/stop` |
| 空 LLM 响应 | Editor / Reviewer 检测空返回抛 RuntimeError，scheduler 重置记录至 PENDING_TOPIC |

---

## 快速开始

```bash
git clone https://github.com/shuaigexly/-multiagent.git
cd -- -multiagent
```

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 LLM 和飞书凭证
```

最小配置（DeepSeek + 飞书中国版）：

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

FEISHU_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 2. 启动后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`

### Docker 启动（可选）

```bash
# 后端
docker build -t puff-backend ./backend
docker run -p 8000:8000 --env-file backend/.env puff-backend

# 前端
docker build -t puff-frontend ./frontend
docker run -p 80:80 puff-frontend
```

---

## 环境变量说明

### LLM 配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | `openai_compatible` 或 `feishu_aily` | `openai_compatible` |
| `LLM_API_KEY` | LLM 服务商 API Key | — |
| `LLM_BASE_URL` | Chat Completions 端点 URL | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
| `AILY_APP_ID` | 飞书 Aily 智能伙伴 App ID（`feishu_aily` 模式时必填） | — |

### 飞书配置

| 变量 | 说明 |
|------|------|
| `FEISHU_REGION` | `cn`（中国版）/ `intl`（Lark 国际版） |
| `FEISHU_APP_ID` | 企业自建应用 App ID |
| `FEISHU_APP_SECRET` | 企业自建应用 App Secret |
| `FEISHU_CHAT_ID` | 默认推送群 ID（可选） |
| `FEISHU_BOT_VERIFICATION_TOKEN` | 机器人验证 Token |
| `FEISHU_BOT_ENCRYPT_KEY` | 机器人加密 Key |

### 内容运营工作流

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `WORKFLOW_INTERVAL_SECONDS` | 调度循环间隔（秒） | `30` |
| `WORKFLOW_ANALYSIS_EVERY` | 每 N 轮触发一次周报生成 | `5` |

### 安全与基础设施

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `API_KEY` | 后端鉴权 Key，留空则无鉴权（**生产必填**） | — |
| `ALLOWED_ORIGINS` | 允许的跨域来源，逗号分隔 | `http://localhost:5173` |
| `DATABASE_URL` | SQLite / PostgreSQL 连接串 | `sqlite+aiosqlite:///./data.db` |
| `REDIS_URL` | Redis 连接串（留空自动降级为 DB 轮询） | — |
| `TOKEN_ENCRYPTION_KEY` | Fernet 对称密钥，加密存储用户 OAuth token | — |
| `TASK_TIMEOUT_SECONDS` | 单次任务最大执行秒数 | `300` |
| `SENTRY_DSN` | Sentry 错误监控（留空不启用） | — |

---

## API 参考

### 任务工作流

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/tasks` | 提交任务，返回 `task_id` 和 AI 推荐方案 |
| `POST` | `/tasks/{id}/confirm` | 确认执行（可调整 Agent 组合） |
| `GET`  | `/tasks/{id}/stream` | SSE 实时执行日志 |
| `GET`  | `/tasks/{id}/results` | 完整分析报告 |

### 飞书数据

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET`  | `/feishu/workspace` | 飞书工作区数据（云盘/日历/任务/群聊） |
| `POST` | `/feishu/publish` | 发布结果到飞书 |
| `GET`  | `/oauth/url` | 获取飞书 OAuth2 授权 URL |
| `GET`  | `/oauth/callback` | OAuth2 回调处理 |
| `GET`  | `/oauth/status` | 查询授权状态 |

### 内容运营工作流

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/workflow/setup` | 创建多维表格结构 + 写入种子任务（循环运行中返回 409） |
| `POST` | `/api/v1/workflow/start` | 启动后台调度循环（已运行返回 400） |
| `POST` | `/api/v1/workflow/stop` | 停止循环（立即生效，不等待当前轮结束） |
| `GET`  | `/api/v1/workflow/status` | 运行状态 + 表格 ID |
| `POST` | `/api/v1/workflow/seed` | 追加待选题任务 |
| `POST` | `/api/v1/workflow/analyze` | 手动触发周报（已在生成中返回 409） |
| `GET`  | `/api/v1/workflow/records` | 查询记录，支持 `?status=已发布` 等过滤 |

### 健康检查

```
GET /health  →  {"status": "ok", "service": "feishu-ai-workbench"}
```

> 设置 `API_KEY` 后，所有请求需携带 `X-API-Key: <your-key>` 请求头。

---

## 飞书应用权限

在[飞书开放平台](https://open.feishu.cn/)创建企业自建应用，配置以下权限：

| 权限 | 用途 |
|------|------|
| `docx:document` | 创建/读写飞书文档 |
| `bitable:app` | 创建/读写多维表格（内容运营工作流必需） |
| `im:message:send_as_bot` | 机器人发送群消息 |
| `task:task:write` | 创建飞书任务（需用户 OAuth 授权） |
| `task:task:readable` | 读取飞书任务列表（需用户 OAuth 授权） |
| `drive:drive:readonly` | 读取云盘文件列表 |
| `calendar:calendar:readonly` | 读取日历事件 |
| `im:chat:readonly` | 获取群组列表 |
| `contact:user.id:readonly` | OAuth 授权后获取用户 open_id |
| `wiki:node:create` | 知识库写入（可选） |

> 飞书任务 API 需用户级授权。在「设置」页点击「授权飞书任务」完成 OAuth 授权后，才能读取和创建任务。

---

## 支持的 LLM 服务商

`LLM_PROVIDER=openai_compatible` 模式支持所有兼容 OpenAI Chat Completions 的服务：

| 服务商 | `LLM_BASE_URL` | 推荐模型 |
|--------|---------------|---------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| DeepSeek（推荐） | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 火山方舟·豆包 | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-pro-32k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 百川 AI | `https://api.baichuan-ai.com/v1` | `Baichuan4-Air` |
| MiniMax | `https://api.minimax.chat/v1` | `MiniMax-Text-01` |
| Ollama（本地） | `http://localhost:11434/v1` | `qwen2.5:7b` |

**飞书 Aily 模式**：设置 `LLM_PROVIDER=feishu_aily` + `AILY_APP_ID`，需企业开通飞书 AI 智能伙伴并申请 `aily:session` 权限。

---

## 国际版 Lark 支持

```env
FEISHU_REGION=intl
```

系统自动切换到 `open.larksuite.com` API 端点，需额外安装：

```bash
pip install larksuite-oapi
```

在 [https://open.larksuite.com/](https://open.larksuite.com/) 创建企业自建应用，其余配置与中国版一致。

---

## 变更日志

### v7.2（当前） — Agent 跨岗 Q&A + 图表渲染 + LLM token 流式

继续把 agent 推向"真实可用"：可互相追问、能产出可视化、思考过程实时透出。

**🤝 跨 agent Q&A 协议（`app/agents/peer_qa.py`）**
- 新工具 `ask_peer(agent_id, question)` —— CEO 助理在汇总时可对 Wave1/2 同侪发起定向追问
- 通过 `ContextVar` 把同侪 `AgentResult` 池注入 Wave3 LLM 调用作用域
- 被问的 peer 拿到自己的完整分析作为上下文，发起短 prompt 二次 LLM 调用回答（200 字内、temperature=0.3）
- 严格防环：peer 在被 ask 时不会再触发 ask_peer
- 解决"CEO 凭静态文本拼凑、信息丢失"的痛点 → 现在能动态澄清"留存率具体多少？"

**📊 自动图表渲染（`app/bitable_workflow/chart_renderer.py`）**
- chart_data JSON → matplotlib PNG bytes（headless Agg backend）
- 上传到飞书云空间 `/drive/v1/medias/upload_all`，附件挂到 Bitable「图表」字段（type=Attachment）
- 支持中文 emoji 标签（DejaVu Sans + 中文 fallback）
- matplotlib 缺失 / 上传失败 / 数据点 < 2 → 优雅降级，仍写文本「图表数据」字段
- schema.py 岗位分析表追加 `图表` 附件字段（FieldType=17 Attachment）

**📡 LLM token 流式输出（`call_llm_streaming`）**
- 新增 `core/llm_client.call_llm_streaming(on_token=...)`，OpenAI streaming 协议
- `base_agent._call_llm` 检测当前 task_id 时自动启用流式，每累计 ~30 字符或换行推一次 `agent.token` SSE 事件
- 前端 `subscribeTaskProgress` 增加 `agent.token` 监听，UI 可实时显示 agent "正在思考"
- include_usage=True 让最后 chunk 仍能记账到 budget tracker
- 环境变量 `LLM_STREAMING=0` 可全局关闭

**🧪 测试**
- 新增 `tests/test_peer_qa_and_chart.py`（5 cases）：peer pool 设置/清理、ask_peer 错误路径、ask_peer LLM 调用上下文、chart 空输入返 None、PNG magic header 校验
- 全套件 65 → **70 passing**

**📦 依赖**
- 新增 `matplotlib==3.9.2`（chart 渲染）

### v7.1 — Agent 真实工具调用 + 多租户传播

本轮聚焦 **agent 实际能力提升**：让 7 岗 LLM 不再凭空估算，而是在分析过程中主动调用工具拉真实数据。

**🛠️ Function calling 工具调用框架（`app/agents/tools.py` + `builtin_tools.py`）**
- OpenAI function calling 协议兼容，每个 agent 在分析中可决定调用工具
- `call_llm_with_tools` 实现工具循环：LLM 决策 → 并行执行工具 → 结果回填 → 再决策（最多 4 轮）
- 每轮检查 budget；超额或达上限自动终止循环并强制收尾
- feishu_aily provider 不支持 function calling，自动回退普通调用

**🧰 4 个内置工具（开箱即用）**
| 工具 | 用途 | 返回 |
|---|---|---|
| `fetch_url(url)` | 抓取公开网页（行业基准、新闻、文档） | 文本（HTML 自动去标签，前 8000 字） |
| `bitable_query(app_token, table_id, filter)` | 查询任何多维表格记录 | JSON 数组（最多 50 条） |
| `feishu_sheet(url)` | 读取**真实飞书电子表格** | 前 100 行 CSV |
| `python_calc(expression)` | 受限 Python 数值计算（math 库 + 列表推导） | 字符串结果（禁 I/O / import / `__`） |

**📥 真实数据源升级**
- v6.0 仅支持把 CSV 文本粘到「数据源」字段
- v7.1 agent 可直接接收飞书 Sheet URL → `feishu_sheet` 工具自动拉真实单元格
- agent 可在中途用 `bitable_query` 查询其他岗位的历史输出（跨任务横向参考）

**🏢 多租户 tenant_id 全链路传播**
- 中间件读取 `X-Tenant-ID` 请求头（缺失为 `default`），写入响应 + observability 上下文
- 所有 LLM budget / agent_cache / audit_log 自动按 tenant 隔离
- 为后续 schema 级多租户演进打基础（task 表加 tenant_id 字段后即可启用）

**🧪 测试**
- 新增 `tests/test_agent_tools.py`（8 cases）：注册器 / dispatch 异常容错 / OpenAI schema / python_calc 沙箱
- 全套件 57 → **65 passing**

**显式延后（理由：本轮已是大改动，独立 PR 更可控）**
- Arq 后台任务系统：当前 BackgroundTasks + scheduler 满足单实例需求；多实例横向扩展时再切
- Alembic 迁移：当前 `init_db.create_all` 还能 cover；schema 频繁变更时再引入

### v7.0 — 企业级基础设施层（可观测性 + 成本管控 + 审计）

为提升项目的运维与生产就绪程度，引入四项基础设施能力：

**🔍 结构化日志 + correlation_id 全链路追踪（`app/core/observability.py`）**
- ContextVar 实现 correlation_id / task_id / agent_id / tenant_id 跨 await 传播
- `LOG_FORMAT=json` 启用 JSON 输出（兼容 Loki / Datadog / CloudWatch 直接消费）；`plain` 为本地开发友好格式
- `correlation_middleware` 自动从 `X-Correlation-ID` / `X-Request-ID` 请求头读取，否则生成 uuid4 短码并写回响应
- scheduler 每条任务进入流水线时自动 `set_task_context(task_id=rid)` —— 此后所有 `logger.*` 调用自动带任务标识
- 抑制 `httpx` / `httpcore` / `openai._base_client` 等三方库的 INFO 噪声

**💰 LLM 成本管控（`app/core/budget.py`）**
- 双层预算闸门：`per_task_token_budget`（单任务上限）+ `daily_token_budget`（租户每日上限）
- 调用前 `check_budget(strict=True)` 拦截，超额抛 `BudgetExceeded`，调用方可降级（关 reflection / 截短 prompt）
- 调用后 `record_usage(prompt_tokens, completion_tokens)` 记账
- 后端：Redis `INCRBY` + TTL 自动归档（task=24h，daily=36h），不可用时进程内 dict fallback
- 三个维度可查：当前任务、当前租户当日、全局当日（运维大盘）

**🩺 K8s 风格健康/就绪探针（`app/api/health.py`）**
- `GET /healthz` —— 仅确认 Python 进程响应（liveness 探针）
- `GET /readyz` —— 并发检查 DB / Redis（optional）/ LLM 配置 / 飞书凭证；critical 失败返回 503
- 每项检查带延迟数据，便于排查依赖慢点
- 旧 `/health` 端点保留为 `/healthz` 别名

**📋 审计日志（`app/core/audit.py` + `models.AuditLog`）**
- Append-only 表 `audit_log`：action / actor / target / tenant_id / correlation_id / payload / result
- `app/api/workflow.py` 关键端点埋点：setup / start / stop / seed
- 写入失败仅 warning，绝不阻塞业务
- 索引覆盖 `(action, created_at)` + `(tenant_id, created_at)`，便于按时间窗 / 租户聚合查询

**🧪 测试**
- 新增 `tests/test_observability_budget.py`：covers correlation_scope / record_usage 累加 / strict 超额 / status 视图（6 cases）
- 全套件 51 → 57 passing

### v6.2 — 二轮审计修复（鲁棒性 + 边界 + 重构）

**🔒 安全 / 并发**
- `scheduler.py` 新增 `_claim_pending_record`：标记 ANALYZING 后回读校验，防止多实例并发"双领取"同一任务
- `scheduler.py` cycle lock 新增续租协程 `_renew_cycle_lock` + 生产环境强制 Redis 锁（`WORKFLOW_ALLOW_LOCAL_LOCK` 显式允许才回退到本地锁）
- `settings.py` 注释强化：`token_encryption_key` 必填，除非显式允许明文存储

**📐 文本边界**
- 新增 `core/text_utils.py::truncate_with_marker`：以字符为单位安全截断 + 追加截断标记，避免在 emoji / 中文边界切坏字节
- 全栈替换散落的 `[:N]` 切片：`base_agent` / `scheduler` / `bitable` / `publisher` / `reader` / `cardkit` / `slides` / `task` / `cli_bridge` / `data_parser` 等 14 文件

**🔄 流水线一致性**
- `workflow_agents` 拆分 `cleanup_prior_task_outputs` 为两段：`collect_prior_task_output_ids` + `cleanup_prior_task_output_ids`，避免清理时遗漏 / 删错
- `base_agent._build_prompt` 改为 async，skill_loader 通过 `asyncio.to_thread` 调用，不再阻塞事件循环

**🧹 重构**
- `feishu/publisher.py` 整体重写（301 行）：统一 doc/bitable/slides/message 的 token 选择 + 错误归一化
- `api/feishu_context.py` 上下文聚合加入超时 + 并发上限
- `api/tasks.py` / `config.py` / `feishu_bot.py` / `feishu_oauth.py` 错误响应规范化

**🧪 测试**
- 新增 `tests/test_security_utils.py`：覆盖 `truncate_with_marker` emoji / 中文 / 边界长度

### v6.1 — 审计阻断项修复

- `core/auth.py` 新增：HMAC stream token（短时签发）替代 query string 传 API key
- `api/workflow.py` 加 `Depends(require_api_key)`；新增 `POST /stream-token/{record_id}` 签发 SSE 短时 token
- `bitable_workflow/scheduler.py` 加分布式 cycle lock（Redis SETNX）+ 仅恢复 stale ANALYZING 记录
- `agent_cache.py` cache key 加输入 hash，避免数据源变更后命中旧结果；Redis 失败 60s 退避重试
- `bitable.py` / `feishu/*` 复用 `httpx.AsyncClient`；先校验 HTTP 状态码再解析 JSON
- `retry.py` 拆分 `_is_non_retryable_value_error`：仅"未配置 / 不支持 / 不能为空 / 缺少 / 需要提供"快速失败
- `runner.py` `_state_lock = threading.Lock()` 守护 `_running` 状态翻转
- 前端：`services/http.ts` 共享 axios 实例统一注入 API key；`subscribeTaskProgress` 改为先取 stream token 再建 EventSource
- 前端依赖 CVE 升级；新增 `test/workflow.test.ts` 覆盖 SSE token 流程

### v6.0 — 视觉化字段 + 真实数据源 + 实时进度流

本轮聚焦"让多维表格像仪表盘一样能一眼看懂"以及"让分析基于真数据"：

**🎨 视觉化字段（告别纯文本）**
- 重写 `schema.py`：利用飞书 28 种字段类型中的 9 种高级类型
  - `SingleSelect` 有色标签：7 岗角色带 emoji（📊 数据分析师 / 📝 内容负责人 / 🔍 SEO顾问 / 📱 产品 / ⚙️ 运营 / 💰 财务 / 👔 CEO）
  - `SingleSelect` 评级：🟢 健康 / 🟡 关注 / 🔴 预警 / ⚪ 数据不足
  - `Rating` 星级：置信度 ⭐ 1-5、决策紧急度 🔥 1-5、员工活跃度 👍 1-5
  - `Progress` 进度条：任务进度 0-100%（Wave 推进 10%→45%→75%→95%→100%）
  - `AutoNumber` 自增任务编号
  - `CreatedTime` / `ModifiedTime` 自动时间戳
- 新增 `bitable.py::create_view()`：每张表自动创建看板 / 画册视图
  - 分析任务表：📊 状态看板 + 📇 任务画册
  - 岗位分析表：👥 岗位看板 + 🩺 健康度画册
  - 综合报告表：🚦 健康度看板（快速定位 🔴 预警）

**🧠 LLM 结构化输出（metadata 块）**
- `base_agent.py` 在每次 LLM 调用的 `SAFETY_PREFIX` 中注入 metadata 要求
- LLM 必须在输出末尾附带 ```metadata``` JSON 块，自报 `health / confidence / actions[]`
- 根治"偷懒占位符"问题（之前 SEO/运营 常吐 `[任务1][具体动作]`）
- `_parse_output` 提取 metadata，覆盖 text 解析的 `action_items`
- text 解析加入占位符过滤（`[任务1]`、`[具体动作]` 等模板关键词直接丢弃）

**📥 真实数据源接入**
- 分析任务表新增「数据源」字段，用户可粘贴 CSV / markdown / 纯文本
- `workflow_agents.run_task_pipeline` 自动识别并解析为 `DataSummary`
- 注入每个 agent 的 `analyze(data_summary=)`，分析基于真数据而非"行业基准估算"

**⚡ Redis agent 缓存（崩溃恢复秒级化）**
- 新增 `agent_cache.py`：每个 agent 的 `AgentResult` 以 JSON 缓存 2 小时
- key=`agent_cache:{task_id}:{agent_id}`；任务成功后自动清除，失败保留供重试复用
- Redis 不可达时静默降级 —— 不影响主流程

**📡 SSE 实时进度流**
- 新增 `progress_broker.py`：进程内 `asyncio.Queue` pub/sub，按 task_id 隔离
- 新增端点 `GET /api/v1/workflow/stream/{record_id}`（基于 `sse-starlette`）
- 事件类型：`task.started` / `wave.completed` / `task.done` / `task.error`

**🛡️ 健壮性**
- `reflection_enabled` 默认改为 `False`：每次分析省一次 LLM 评审调用，端到端 -25% 耗时
- `retry.py`：Bitable `LinkFieldConvFail` (1254067) 加入 fast-fail 集；`ValueError` 配置缺失立即失败（不再盲目重试 3 次）
- `aiosqlite` 加入依赖，修 `batch_create_tasks` → `user_token` 初始化链断层
- 飞书原生 Tasks API 集成：CEO 行动项自动同步到飞书待办中心

### v5.0

**七岗多智能体虚拟组织 + 业务完整闭环**

- **表间关联记录**：岗位分析表、综合报告表通过飞书关联字段（type=18）与分析任务主表关联，实现真正的多维表格表间关系而非文本复制
- **业务反馈闭环（再流转）**：CEO 助理输出的行动项自动写回分析任务表，系统持续自驱运行，不依赖人工补任务
- **飞书消息推送**：每条任务完成后向配置群推送 CEO 报告摘要卡片，实现 Agent 员工主动通知
- **默认模型切换为 DeepSeek**：`deepseek-chat` 作为系统默认模型，符合竞赛国内模型要求
- **完整测试套件**：新增 `backend/tests/` 目录，覆盖 schema 字段定义、流水线逻辑、调度器状态机的单元测试
- Token 双检锁（thundering-herd 防护）、httpx 连接复用、CancelledError 正确传播等健壮性修复

### v4.0

**七岗多智能体工作流**

- 将 bitable_workflow 重构为七岗 DAG 流水线（Wave1 五并行 → Wave2 财务顾问 → Wave3 CEO 助理）
- 四张多维表格：分析任务 / 岗位分析 / 综合报告 / 数字员工效能
- 崩溃恢复：Phase 0 每轮重置遗留 ANALYZING 记录
- 完成度校验：岗位分析写入不完整时整条任务回滚重试

### v3.0

- **飞书 OAuth 用户授权**：完整 OAuth2 流程，user_access_token 持久化到数据库，服务重启自动恢复
- **飞书上下文读取**：自动读取关联飞书文档正文作为 Agent 分析数据源
- **飞书工作区页面**：独立浏览页，支持文档/日历/任务/群聊四 Tab 查看
- **富文本文档发布**：doc.py 升级为结构化块（heading/callout/bullet/divider）
- **增强多维表格**：双表结构（行动清单含单选字段 + 分析摘要表）
- **演示文稿发布**：slides.py 三层降级（lark-cli → Presentation API → 结构化文档）

### v2.0

- **多 Agent 波次架构**：依赖感知执行，data_analyst → finance_advisor → ceo_assistant 按序推进
- **双层重试机制**：Agent 级别（3 次）+ LLM 调用级别（3 次）指数退避
- **AutoGen 反思机制**：每个 Agent 输出后自动质量评审
- **上游上下文增强**：下游 Agent 获得完整上游分析（全章节 + 行动项）
- **前端执行日志重设计**：Agent 活动卡片网格替代终端文字日志

### v1.0

- 多 Agent 并行执行 MVP
- SSE 实时日志推送
- 飞书文档/多维表格/消息发布
