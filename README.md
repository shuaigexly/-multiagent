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

### 内容运营工作流：三个 AI 数字员工

```
① 用户在多维表格写入待选题任务
② 内容编辑 AI 自动领取、撰写草稿
③ 内容审核员 AI 自动审核、评分、决定发布或拒绝
④ 运营分析师 AI 定期汇总数据、生成周报
⑤ 所有操作实时回写飞书多维表格，全流程可追溯
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

## 内容运营虚拟组织

本模块实现「三个 AI 数字员工」自动协作，通过飞书多维表格驱动完整的内容生产流水线。

### 状态流转

```
待选题 ──[EditorAgent]──▶ 写作中 ──▶ 待审核 ──[ReviewerAgent]──▶ 已发布
                                                               └──▶ 审核拒绝
                                          [AnalystAgent 每 N 轮] ──▶ 已分析
```

### 三张多维表格

| 表格 | 用途 | 核心字段 |
|------|------|----------|
| **内容任务** | 任务主表，驱动状态机 | 标题、内容类型、状态、草稿内容、审核意见、质量评分、发布时间 |
| **员工效能** | 各 Agent 处理量与质量统计 | 员工姓名、角色、处理任务数、通过率、平均质量分、已评分任务数 |
| **周报** | 运营分析师生成的周期性报告 | 报告周期、总产出、通过率、摘要、关键指标、改进建议 |

**内容类型**：`行业洞察` / `产品介绍` / `用户故事` / `数据分析`

### 工作流 REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/workflow/setup` | 一键创建多维表格结构，写入 4 条种子任务 |
| `POST` | `/api/v1/workflow/start` | 启动后台调度循环 |
| `POST` | `/api/v1/workflow/stop` | 停止调度循环（立即生效） |
| `GET`  | `/api/v1/workflow/status` | 查看运行状态和表格信息 |
| `POST` | `/api/v1/workflow/seed` | 向内容任务表写入一条新的待选题 |
| `POST` | `/api/v1/workflow/analyze` | 手动触发运营分析师生成周报（已在生成中返回 409） |
| `GET`  | `/api/v1/workflow/records` | 查询多维表格记录，支持 `?status=` 过滤 |

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
│   ├── schema.py         # 多维表格结构常量（字段定义、状态枚举、种子数据）
│   ├── bitable_ops.py    # 多维表格记录 CRUD（直接 HTTP，with_retry 指数退避）
│   ├── workflow_agents.py# EditorAgent / ReviewerAgent / AnalystAgent
│   ├── scheduler.py      # 状态驱动调度（Phase 0 崩溃恢复 + Phase 1/2 处理，最多 5 条/轮）
│   └── runner.py         # setup_workflow / run_workflow_loop / stop_workflow / mark_starting
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
│   ├── Index.tsx           # 工作台主页（任务输入 + 模块选择 + 执行监控）
│   ├── ResultView.tsx      # 结果详情（分节报告 + 行动项 + 飞书发布）
│   ├── FeishuWorkspace.tsx # 飞书工作区（云盘/日历/任务/群聊 四 Tab）
│   ├── Settings.tsx        # 设置页（LLM + 飞书配置 + OAuth 授权）
│   └── History.tsx         # 任务历史列表
└── components/
    ├── ExecutionTimeline.tsx   # 执行日志（Agent 活动卡片 + 时间线）
    ├── ModuleCard.tsx          # Agent 选择卡片（含 persona 信息）
    ├── ContextSuggestions.tsx  # 飞书上下文智能推荐
    └── FeishuAssetCard.tsx     # 发布资产卡片（doc/bitable/slides/message）
```

### 关键工程设计

| 问题 | 方案 |
|------|------|
| 多 Agent 依赖关系 | DAG 拓扑排序，按波次并发执行，下游获得完整上游上下文 |
| 调度循环重入防护 | `mark_starting()` 在请求处理函数内同步置 `_running=True`，后台任务启动前对外可见 |
| 分析报告并发防护 | `asyncio.Lock`（`analyze_lock`）在 runner 和 API 层共享，手动触发返回 409 |
| Bitable API 可靠性 | 全部 CRUD 套 `with_retry(max_attempts=3, base_delay=1s)` 指数退避 |
| 崩溃恢复 | Phase 0 每轮把遗留 WRITING 记录重置为 PENDING_TOPIC |
| 效能统计不失真 | 滚动平均分用独立 `已评分任务数` 做分母，不被未评分任务稀释 |
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
| `LLM_BASE_URL` | Chat Completions 端点 URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型名称 | `gpt-4o-mini` |
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

### v4.0（当前）

**内容运营虚拟组织工作流**

- 新增 `bitable_workflow` 模块：三个 AI 数字员工（内容编辑、内容审核员、运营分析师）通过飞书多维表格驱动完整内容生产流水线
- 状态机：`待选题 → 写作中 → 待审核 → 已发布/审核拒绝 → 已分析`，完整覆盖内容生命周期
- **崩溃恢复**：Phase 0 每轮自动检测并重置遗留 WRITING 记录，保证进程重启后数据一致性
- **员工效能追踪**：滚动平均分使用独立 `已评分任务数` 分母，避免未评分任务稀释统计
- **分析报告并发防护**：`asyncio.Lock` 在后台循环和手动触发 API 间共享，杜绝重复周报
- **调度循环重入防护**：`mark_starting()` 在请求函数内同步置位，防止快速双击 `/start` 产生两个并发循环
- **全量 Bitable CRUD 重试**：`with_retry(max_attempts=3)` 指数退避，处理网络抖动和 429 限流
- **空响应防护**：Editor / Reviewer 对空 LLM 回复抛 RuntimeError，而非静默写入损坏数据
- **`/setup` 并发保护**：循环运行时调用返回 409，防止孤立表格

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
