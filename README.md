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

### v8.2（当前） — 第十 ~ 十四轮审计（4 个真实 bug + 1 dead code）

🔴 严重 — 全部都是同款"懒初始化 race"系统性问题：
36. `bitable_ops._get_http_client` race — 并发 Bitable 请求各自创建 httpx client，winner 之外的 client 永不 close → FD + connection pool 泄漏（持续累积可耗尽 sockets）。
37. `feishu/bitable._get_http_client` 同款 race — Feishu Bitable HTTP client 同样泄漏。
38. **`llm_client._get_llm_semaphore` 同款 race** — 并发首次 LLM 调用各自创建独立 Semaphore(2)，**全局并发限流彻底失效**（实际可能 4-6 个 LLM 同时跑）→ 频繁触发 429 rate limit，是用户感知最强的 bug。

修复：所有 4 个 module-level lazy singleton 全部统一为 `threading.Lock` 双检模式（与 v8.0/v8.1 相同的 idiom）：
- `_init_lock = threading.Lock()` 守护"创建"步骤
- 双检：外检 + 锁内检 → 仅一个线程构造，其余直接拿现有实例

🟢 清理：
- `_extract_health` 删除未使用的 `emoji` 局部变量（旧实现遗留）

🧪 测试：
- 全套件保持 **154/154 passing**（无新测试 — 修复为内部线程安全，行为不变；既有 test_audit_round4 等已覆盖懒初始化 race 通用模式）

### v8.1 — 第八 + 九轮审计（5 个真实 bug）

继续深扫，又找到 5 个真实 bug。

🔴 严重：
31. **`feishu_context.py` `isinstance(x, Exception)` 漏 `CancelledError`** — Python 3.8+ `CancelledError` 继承 `BaseException` 而非 `Exception`。客户端断 SSE → 子调用被 cancel → cancelled 对象当 drive 数据返回 → JSON 序列化抛错。修：用 `isinstance(x, BaseException)` + 显式重 raise CancelledError。
32. **`aily._get_token_lock` 懒初始化 race** — 与 progress_broker 同款。两个并发首次调用各自创建 Lock → 双重 fetch tenant_access_token 浪费 Feishu 配额。修：`threading.Lock` 双检守护。
33. **`api/tasks._get_claim_lock` 同款 race** — 任务认领串行化失效。修：双检锁。
34. **`scheduler._LOCAL_CYCLE_LOCK` 同款 race** — cycle 互斥失效。修：双检锁。
35. **Pillow ≥ 10 弃用 `Image.LANCZOS`** — 升级 Pillow 后图像缩放抛 AttributeError。修：双路径 fallback `Image.Resampling.LANCZOS` → `Image.LANCZOS`。

🧪 测试：
- 新增 `tests/test_audit_round5.py`（5 cases）：CancelledError 父类验证 / 3 处懒初始化锁单例 / Pillow LANCZOS 双兼容
- 全套件 149 → **154 passing**（+2 skipped 环境兼容）

### v8.0 — 第四 + 五 + 六 + 七轮审计（9 个真实 bug）

**🔴 严重**
22. `progress_broker._get_lock` 懒初始化 race — 两个 coroutine 并发首次访问各自创建 Lock，publish 用 A 锁、subscribe 用 B 锁 → 订阅者列表无同步。修：threading.Lock 双检守护 asyncio.Lock 的"创建"步骤。
23. `agent_cache._get_redis` 同款懒初始化 race → winner 之外的连接全部泄漏。修：asyncio.Lock 双检锁。
24. `budget._get_redis` 同款 race。修：asyncio.Lock 双检锁。
25. **优先级排序 pool 太小** — `_MAX_PER_CYCLE × 4 = 12` 候选过少：50 个 PENDING 任务，前 12 都是 P3 → 后面的 P0 任务永远不会被领取。修：bump 到 200 + `WORKFLOW_PENDING_POOL_SIZE` env 可调。
27. **流式还是有死代码 v2** — `is_final_iter` 仅在 LLM 耗尽 4 轮工具迭代时触发流式。多数任务 LLM 第一轮就给内容，永远走不到流式分支。修：当 LLM 给出最终 content 且 `on_token` 在场时，把内容作为一条事件通过 callback 推送出去。
29. **流式中途异常丢失已累积 chunks** — `async for event in stream` 在 try 块内，网络抖动让所有累积 token 全丢。修：内层 try/except 保留 partial 内容，仅在 partial 为空时 raise。
30. `call_llm_streaming` 同款问题。修：同样的 partial-保留逻辑。

**🟡 中**
26. `parse_content` 大 CSV 阻塞事件循环（pandas 同步 + 重 import）→ 同时阻塞 SSE / 健康检查。修：`asyncio.to_thread` 包装。
28. `METADATA_REQUIREMENT` 重复定义 — 第一版 20+ 行 prompt 每次构造后被覆盖丢弃，GC 压力 + 维护陷阱（人改第一版无效）。修：删除被覆盖版本。

**🧪 测试**
- 新增 `tests/test_audit_round4.py`（6 cases）：
  - progress_broker 并发 _get_lock 单例
  - agent_cache + budget 双检锁防泄漏
  - Redis 失败 retry_at 守卫
  - 优先级 pool size ≥ 100
  - parse_content 在线程池而非主循环执行
- 全套件 143 → **149 passing**（+1 skipped 是 FastAPI 版本兼容跳过项）

### v7.9 — 第三轮审计修复（再清 5 个 bug）

🔴 严重：
17. `_extract_first_json_array` 转义符在字符串外被处理 → `\]` 之类的字符让深度计数错乱。修：把转义/引号判定限定在 `in_str=True` 分支内，字符串外只看 `[`/`]`/`"`。
18. PIL 图像模式覆盖不全 — 只转 RGBA/P 漏 L/1/CMYK/I/PA → JPEG `save()` 在这些模式上抛 `OSError`。修：`if img.mode != "RGB": img.convert("RGB")` 一刀切。
19. `_check_redis` ping 超时不走 `aclose` → 健康探针每次失败漏一个 Redis 连接。修：try/except/finally 保证关闭。
20. **Plan-execute execute 阶段 system_prompt 退化**：之前用了弱版本 `f"你是「{name}」..."`，agent 几千字的领域 SYSTEM_PROMPT（RICE/JTBD/RFM 等专业框架）在 5 个子问题里全部失效，子问题答案变成"通用车轱辘话"。修：保留 agent 的 SYSTEM_PROMPT 前 1500 字 + 子问题约束。
21. 优先级排序仅识别精确字符串 `"P0 紧急"` — 用户填 `P0` / `紧急` / `p1` 都被降到优先级 99。修：宽松匹配（包含 P0/紧急/高/中/低 关键词）。

🧪 测试：
- `tests/test_audit_round3.py`（7 cases）：
  - 转义符在字符串内/外的两条路径
  - 字符串内含 `]` 不让深度提前归零
  - 优先级宽松匹配 6 种用户输入
  - Redis aclose 在 ping 超时仍被调用
  - Plan-execute exec 阶段 system_prompt 含 agent persona 关键词
  - PIL 全模式（RGBA/P/L/1/CMYK/I/PA）转 JPEG
- 全套件 136 → **143 passing**

### v7.8 — 第二轮审计修复（继续清 bug）

第一轮把表面问题修了，再深翻一遍又找出 6 个真实 bug，每条都加回归测试。

**🔴 严重**
11. **流式 LLM 路径是死代码** — 启动时 `builtin_tools` 自动注册 4 个工具，`tools_available` 永远为 True → `call_llm_with_tools` 分支抢占，前端 SSE `agent.token` 事件**永远不会被发送**。修：`call_llm_with_tools` 加 `on_token` 参数，最后一轮（强制 `tool_choice=none`）走流式协议；`base_agent` 把 SSE callback 透传过去。
12. **`.format()` 在含花括号的输入下抛 `KeyError`** — `plan_execute` 三个 prompt + `judge` + `prompt_evolution` 五处用 `.format()`。任务描述含 `{"users": ...}` 这类 JSON 直接崩。base_agent 早就改成 replace 了，新模块全部退化回 format。修：5 处全改为 `.replace("{key}", val)`。
13. **Vision base64 大图爆 context** — 5MB 截图 → base64 7MB → ~1.7M tokens。修：4MB 原始上限 + 600KB 压缩阈值，超过时 PIL 自动 thumbnail (1280px) + JPEG 75 质量；PIL 缺失时 warn 并跳过大图。
14. **Plan JSON 解析在 LLM 加废话时直接崩** — LLM 回答常带 "Sure, here is the plan:" 前置文本或末尾解释。原解析仅去 `\`\`\`json` 围栏，前置普通文本就 `json.loads` 失败 → plan-execute 整段抛错回退到单轮 prompt。修：新增 `_extract_first_json_array(text)` 用栈式扫描提取第一个完整 `[...]`，正确处理嵌套、字符串内方括号、转义字符。

**🟡 中**
15. on_token 同时支持 sync / async — 已通过 `asyncio.iscoroutine` 处理。审计确认无问题。
16. **Memory 存了带 `[REDACTED:]` 标记的任务** — sanitize 在 analyze 入口提前做了，被 redact 的任务文本仍被 `store_memory` 存入 → 后续召回让 LLM 看到 `[REDACTED:]` 标记反而暗示了攻击痕迹存在。修：`store_memory` 检测到 `[REDACTED:]` 直接跳过入库。

**🧪 测试**
- 新增 `tests/test_audit_round2.py`（12 cases）：
  - `_extract_first_json_array` 6 路径（clean / 围栏 / 前置废话 / 嵌套 / 字符串内方括号 / 垃圾）
  - 5 个 prompt 改用 replace 不再炸 KeyError
  - `store_memory` REDACTED 任务跳过 + 干净任务正常写入对照
  - `call_llm_with_tools` 签名含 `on_token`（防回归死代码）
- 全套件 124 → **136 passing**

### v7.7 — 审计修复（v7.x 真实 bug 清算）

对 v7.0 → v7.6 全量审计，发现并修复 10 个真实 bug。每条都附回归测试。

**🔴 严重**
1. `_safe_analyze` 把 FALLBACK 兜底结果写进 shared cache → **一次 LLM 失败污染整个分析维度**的所有后续任务。修：FALLBACK 不写 shared，且要求 confidence ≥ 3 才进 shared。
2. CEO plan-execute 成本爆炸：5 步 execute × 4 工具迭代 + plan + synth = **单任务最多 24 次 LLM 调用**。修：execute 阶段直接走 `call_llm` (FAST 档) 不进工具循环；工具调用集中在 synthesize 阶段。
3. Vision 处理飞书附件构造的 URL `?access_token=xxx` 不带 Auth header → vision LLM 永远 401。修：后端先下载字节，base64 → data URI 喂给 vision API。
4. `AgentMemory.kind` 新列在旧库不会被 `create_all` 加上 → INSERT 直接 SQL 失败。修：新增通用 `_ensure_column` 幂等迁移，`init_db` 中调用。
5. `_unmet_dependencies` 用 `lstrip("T0")` 是 char-set 剥离，**任务编号 100 / T100 都会被错剥成 "1"** → 100 号任务做依赖永远查不到。修：换正则 `^[Tt]?0*(\d+)$` 精确匹配。

**🟡 中**
6. `prompt_guard` 漏掉 `feishu_context` — 飞书文档/任务/日历是用户可控内容，恶意文档可绕过 injection 防护。修：`_safe_prompt_text` 集成 sanitize（长度 > 30 字才检测，避免误伤名字/时间戳）。
7. `analyze` 中 memory query 用未消毒的 `task_description` → 攻击文本污染 embedding 库 + 后续任务召回时再被消毒（双重处理）。修：`analyze` 入口统一消毒一次，`_build_prompt` 不再重复处理。
8. Plan-execute 跳过长期记忆 + 反思 hints 注入 → CEO 用 plan-execute 路径时丧失"经验内化"。修：`memory_block` 通过参数透传到 plan/synthesize 两阶段。
9. `_write_reflection` 用 `asyncio.create_task` fire-and-forget 但未持有强引用 → Python 3.12 GC 风险，反思可能在执行中被回收。修：`_BACKGROUND_TASKS` 强引用集合 + `add_done_callback(discard)`。
10. CEO 的 reflection / peer_qa 等内部 LLM 调用通过 `self._call_llm` 会触发 SYSTEM_PROMPT + tools + streaming，不必要的开销。已确认走 `call_llm` 直接路径（修复时已发现 ask_peer / reflection 已经是直接调用，无需改）。

**🧪 测试**
- 新增 `tests/test_audit_fixes.py`（9 cases）：
  - `_normalize_task_number` 边界（T100 / 0010 / 100 / 空 / 异常）
  - `_unmet_dependencies` 100 号任务依赖回归
  - `_safe_analyze` FALLBACK 不写两层 cache
  - `_ensure_column` 幂等迁移
  - `_safe_prompt_text` sanitize 长内容 + 短串豁免
- 全套件 115 → **124 passing**

### v7.6 — Prompt 自演化 + 任务依赖图

让 agent 真正"越用越聪明"，让多任务能形成 DAG 业务流。

**🌱 Prompt 自演化（`app/core/prompt_evolution.py` + `models.AgentPromptHint`）**
- 每次 agent 写完反思后，FAST 档 LLM 给反思打分（0-10）+ 提炼成 1-2 句祈使句
- 4 维评判：普适性 / 可执行 / 简洁性 / 不重复；分数 ≥ 8 才 promote
- 落库 `agent_prompt_hint` 表：`(tenant_id, agent_id, rule_text, score, active)`
- FIFO cap：每个 (tenant, agent) 最多 5 条 active；超出 → 最旧的 active=0
- 重复规则去重（同 rule_text 直接复用，不写新行）
- `base_agent._call_llm` 启动时调 `fetch_active_hints(agent_id)` 拼到 SYSTEM_PROMPT 末尾
- 形成正反馈：agent 反思 → 高分 promote → 下次任务 system_prompt 自动带这条经验
- 环境变量 `LLM_PROMPT_EVOLUTION=0` 关闭

**🔗 任务依赖图（schema + scheduler）**
- 分析任务表新增「依赖任务编号」文本字段：用户填 `1, 3` 或 `T0001, T0003`
- scheduler 启动 cycle 时构建全表 `任务编号 → 状态` 索引
- 每条 pending 任务先检查依赖：所有依赖任务 `已完成` 才能领取，否则当前阶段写「⏸ 等待依赖任务：T0001(分析中)」
- 容错宽松：支持中文分号/换行/逗号/T 前缀混用；引用不存在的任务编号视为未完成
- 形成简单 DAG：A 完成 → 触发 B；B+C 完成 → 触发 D（用户在 Bitable 里填好依赖即可）

**🧪 测试**
- 新增 `tests/test_evolution_deps.py`（13 cases）：
  - prompt promote 各分支（低分跳过/SKIP/解析失败/写入成功/dedup）
  - dep 解析（空/全完成/部分待定/未知/中文分隔/T 前缀/换行）
- 全套件 102 → **115 passing**

### v7.5 — Multi-modal Vision / 反思日志 / 优先级 + DAG 共享

**👁️ Multi-modal Vision（`app/core/vision.py` + `inspect_image` 工具）**
- 适配任意 OpenAI vision 协议模型：GLM-4V / GPT-4o / DeepSeek-VL / Qwen-VL
- 环境变量 `LLM_VISION_MODEL` 启用；缺失自动降级（仅文本管线）
- `inspect_image(image, focus)` 注册为 agent 可调工具：image 接受 URL / data URI / 裸 base64
- 自动注入：分析任务表新增「任务图像」附件字段，`run_task_pipeline` 启动时自动调 vision LLM 把图片转文字 + 拼到 task_description
- 用户可粘截图/手写白板/图表照 → agent 直接基于真实视觉信息分析

**🧠 Agent 自我反思日志**
- `AgentMemory` 表新增 `kind` 列：`case`（任务输出）/ `reflection`（自评经验）
- `analyze` 完成后异步触发：用 FAST 档调 LLM 写 150 字反思（做得好/不够/下次该怎么做）
- 入库 `kind=reflection`；下次任务召回时 reflection **优先于** case 出现在 prompt 中
- `format_memory_hits` 自动分组渲染：「经验教训」段在前，「相似案例」段在后
- 环境变量 `LLM_REFLECTION_LOG=0` 可关闭

**⏱️ 优先级队列（scheduler）**
- `list_records` 拉取 `_MAX_PER_CYCLE × 4` 候选 → 本地按 P0 紧急 / P1 高 / P2 中 / P3 低排序 → 取 top N
- 紧急任务永远先跑，避免被早期插入的 P3 任务阻塞

**🔄 跨任务 DAG 共享（agent_cache shared layer）**
- 新增 `get_shared_result` / `set_shared_result`：key 为 `(dimension, agent_id, input_hash)`
- `_safe_analyze` cache 查找两层：
  1. task-specific（同任务重试复用）
  2. shared（跨任务复用 — 同维度 + 同输入哈希直接复用 Wave1 输出）
- 批量同维度任务（如全部「数据复盘」）跨任务可共享 5 个 Wave1 agent 结果，省 5 次 LLM 调用
- shared cache 命中时自动回填 task cache 加速本任务后续重试

**🧪 测试**
- 新增 `tests/test_v75_features.py`（8 cases）：vision 工具降级 / vision 调用透传 / memory 反思优先 / shared key 隔离维度 / 优先级排序
- 全套件 95 → **102 passing**

### v7.4 — Plan-Execute / LLM-Judge / 规则降级 / Prompt Injection 防护

把 agent 推向真正的"分层思考 + 韧性 + 安全"。

**🎯 Plan-and-Execute 模式（`app/agents/plan_execute.py`）**
- 三阶段执行：**Plan**（LLM 列 3-5 个独立子问题 JSON）→ **Execute**（每个子问题单独调 LLM 可调工具）→ **Synthesize**（用 DEEP 档综合所有子答案）
- 解决"一次性大 prompt 让 LLM 同时承担列结构 + 找数据 + 写结论"的质量问题
- 通过类属性 `plan_execute_enabled = True` 启用；当前 CEO 助理默认启用
- 任一阶段失败 → 自动回退普通单轮 prompt（不阻塞）

**⚖️ LLM-as-Judge 双模型对比（`app/agents/judge.py`）**
- `judge_best(task, candidates: list[str]) → idx`：DEEP 档模型按 4 维权重评判（量化 40% / 逻辑 30% / 完整度 20% / 行动可执行 10%）
- `ab_judge_enabled = True` 的 agent 同时跑 STANDARD + DEEP 两版，judge 选优
- judge LLM 失败 → 自动回退"选最长"启发式
- 重要：plan_execute 已用 DEEP，不再叠加 ab_judge（避免成本翻倍）

**🛡️ 规则引擎降级链路（`app/agents/fallback.py`）**
- `_safe_analyze` 捕获 LLM 异常时，不再直接返 ERROR
- `build_fallback_result` 基于 agent persona + upstream 输出骨架报告：包含 3+ sections / 1+ action_item / confidence=1 / health=⚪
- raw_output 用 `FALLBACK:` 前缀；`_is_failed_result` 不视为硬失败，下游继续
- 7 岗各有专属 persona（FALLBACK_FOCUS + DEFAULT_ACTION），CEO 拿到的"上游"也包含 fallback 结果时仍能产出可读报告

**🔒 Prompt Injection 防护（`app/core/prompt_guard.py`）**
- 11 种高危模式检测（中英）：
  - `ignore previous instructions` / `disregard system` / `you are now ...` / `act as DAN`
  - 中文：忽略以上指令 / 忘记之前对话 / 你现在是 root
  - XML 标签注入：`</user_task><system>...`
  - 控制字符
- 命中 → 用 `[REDACTED:pattern_name]` 替换 + `logger.warning("prompt_injection.detected")` 审计
- `_build_prompt` 自动消毒 `task_description` / `data_summary.full_text` / `user_instructions`
- 攻击事件可在 `audit_log` 通过 correlation_id 追溯

**🧪 测试**
- 新增 `tests/test_advanced_agent.py`（13 cases）：4 路径覆盖中英 jailbreak / fallback persona / judge LLM 解析 / judge fallback
- 全套件 82 → **95 passing**

### v7.3 — 多模型路由 + 长期记忆 + 自动质量重试 + Arq/Alembic 骨架

**🎯 多模型路由（`app/core/model_router.py`）**
- 三档：FAST（GLM-4-flash 等成本档）/ STANDARD（默认）/ DEEP（GLM-4-plus / DeepSeek-R1 等深度档）
- `select_tier(agent_id, prompt_len, retry_attempt, confidence, is_summarizer)` 启发式选档：
  - confidence < 3 或 retry > 0 → DEEP（质量重试）
  - CEO 助理 / 综合任务 → DEEP
  - 短 prompt（< 800）非财务岗 → FAST
- 环境变量 `LLM_FAST_MODEL` / `LLM_DEEP_MODEL` + 各自 `BASE_URL` / `API_KEY` 独立配置；缺省自动回退 STANDARD
- llm_client.call_llm / call_llm_streaming / call_llm_with_tools 全部接受 `tier=` 参数

**🧠 Agent 长期记忆（`app/core/memory.py` + `models.AgentMemory` 表）**
- 同岗位过往任务召回：每次 `analyze` 自动检索最相似 top-3 案例注入 prompt
- 嵌入：优先 OpenAI 兼容 embeddings 接口（设 `LLM_EMBEDDING_MODEL` 启用，如 `embedding-2`），缺失自动回退 hash-based BoW（128 维，中英混合，离线可用）
- 相似度：纯 Python cosine，无 numpy/qdrant 依赖
- 自动按 `tenant_id` 隔离；保留每岗最近 200 条扫描，min_similarity=0.25 过滤
- analyze 完成后落库 task_text + summary + embedding；失败仅 warning

**🔁 自动质量重试**
- agent 输出后若 `confidence_hint < 3` → 自动用 DEEP 档 + retry_hint 重跑一次
- 只有重试 confidence 真的提高才采纳；失败保留原版本
- 环境变量 `LLM_QUALITY_RETRY=0` 关闭、`LLM_QUALITY_RETRY_THRESHOLD=N` 调阈值（默认 3）

**📦 Arq 后台队列骨架（`app/core/arq_queue.py`）**
- 通过 `USE_ARQ_QUEUE=1` 启用；`workflow_cycle_job` 即一次 `run_one_cycle`
- 启动 worker：`python -m arq app.core.arq_queue.WorkerSettings`
- 未启用时继续走 BackgroundTasks 路径，零侵入
- 为多实例横向扩展做准备（当前单进程足够）

**🗄️ Alembic 迁移骨架（`alembic/`）**
- 配置 async SQLAlchemy 兼容的 env.py，从 `settings.database_url` 自动注入
- 第一次：`alembic revision --autogenerate -m "init schema"` → `alembic upgrade head`
- `init_db.create_all` 仍然兜底，迁移用于后续可控演进

**🧪 测试**
- 新增 `tests/test_router_memory.py`（12 cases）：tier 启发式选择、env 回退、hash embedding 一致性、相似度排序、prompt 渲染
- 全套件 70 → **82 passing**

**📦 依赖**
- `alembic==1.13.3` + `arq==0.26.1`

### v7.2 — Agent 跨岗 Q&A + 图表渲染 + LLM token 流式

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
