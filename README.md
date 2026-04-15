# 飞书 AI 工作台

> 飞书 AI 挑战赛参赛项目 · 开放创新赛道

面向复杂任务的飞书 AI 工作台：用户描述任务，AI 自动识别类型、调用多 Agent 模块协同分析、结果实时同步飞书。

---

## 产品定位

当前飞书 CLI/Agent 能力停留在通用性执行——用户给指令，系统执行单一任务，用户仍需自己判断任务类型、应调用哪些工具。

**本产品填补这个缺口**：企业在经营分析、立项评估、风险分析、内容规划等复杂任务上的产品化入口。

---

## 核心流程

```
① 用户描述任务（文字 / 上传文件）
② AI 自动识别任务类型，推荐分析模块组合
③ 用户确认 / 调整模块组合（或手动指定）
④ 多 Agent 依赖感知波次执行，CEO 助理最后汇总
⑤ 结果同步到飞书（文档 / 多维表格 / 群消息 / 任务）
```

---

## Agent 模块

| 模块 ID | 中文名 | 职责 | 执行顺序 |
|---------|--------|------|----------|
| `data_analyst` | 数据分析师 | 数据趋势、异常、核心指标洞察 | 第一波（无依赖） |
| `finance_advisor` | 财务顾问 | 收支结构、现金流、财务风险 | 第二波（依赖 data_analyst） |
| `seo_advisor` | SEO/增长顾问 | 流量结构、关键词机会、内容增长 | 第一波（无依赖） |
| `content_manager` | 内容负责人 | 文档写作、知识库整理、内容归档 | 第一波（无依赖） |
| `product_manager` | 产品经理 | 需求分析、PRD、产品路线图 | 第一波（无依赖） |
| `operations_manager` | 运营负责人 | 行动拆解、任务分配、执行跟进 | 第一波（无依赖） |
| `ceo_assistant` | CEO 助理 | 汇总所有结论，生成管理决策摘要 | 最后波（依赖所有上游） |

---

## 技术架构

```
frontend/   React 18 + TypeScript + Tailwind CSS + shadcn/ui + Vite
backend/    FastAPI + SQLite + asyncio + lark-oapi
```

### 后端核心模块

```
backend/app/
├── api/              # FastAPI 路由层
│   ├── tasks.py      # POST /tasks（提交任务）、POST /tasks/{id}/confirm（确认执行）
│   ├── events.py     # GET /tasks/{id}/stream（SSE 实时日志）
│   ├── results.py    # GET /tasks/{id}/results（获取完整报告）
│   └── feishu.py     # 飞书数据读写：文档/日历/任务/群聊/发布
├── agents/           # Agent 模块
│   ├── base_agent.py # 基类：prompt 构建、LLM 调用、反思机制、输出解析
│   ├── registry.py   # 注册表 + 依赖图 AGENT_DEPENDENCIES
│   └── [7 agents]    # 各 Agent：SYSTEM_PROMPT + USER_PROMPT_TEMPLATE
├── core/
│   ├── orchestrator.py   # 波次执行调度 + 重试
│   ├── task_planner.py   # LLM 任务路由（识别类型 + 推荐模块）
│   ├── llm_client.py     # LLM 调用工厂（含重试）
│   ├── event_emitter.py  # SSE 事件推送
│   └── data_parser.py    # 文件解析（CSV/TXT/MD）
└── feishu/           # 飞书 SDK 封装（文档/多维表/消息/任务/知识库）
```

### 前端核心页面

```
frontend/src/
├── pages/
│   ├── Index.tsx       # 工作台主页（任务输入 + 模块选择 + 执行监控）
│   └── ResultView.tsx  # 结果详情（分节报告 + 行动项 + 飞书发布）
├── components/
│   ├── ExecutionTimeline.tsx   # 执行日志（Agent 活动卡片 + 系统事件时间线）
│   ├── ModuleCard.tsx          # Agent 选择卡片（含 persona 信息）
│   └── ContextSuggestions.tsx  # 飞书上下文智能推荐卡片
└── services/
    ├── api.ts      # 后端 API 调用
    └── feishu.ts   # 飞书数据拉取
```

---

## 快速开始

```bash
git clone --recurse-submodules https://github.com/shuaigexly/multiagent-lark.git
cd multiagent-lark
```

### 1. 配置环境变量

```bash
cp .env.example backend/.env
# 编辑 backend/.env：
# LLM_PROVIDER=openai_compatible
# LLM_API_KEY=sk-xxx
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_MODEL=gpt-4o
# FEISHU_APP_ID=cli_xxx
# FEISHU_APP_SECRET=xxx
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
cp .env.example .env   # VITE_API_URL=http://localhost:8000
npm run dev
```

访问 http://localhost:5173

---

## 飞书应用权限

在[飞书开放平台](https://open.feishu.cn/)创建企业自建应用，需配置以下权限：

| 权限 | 用途 |
|------|------|
| `docx:document` | 创建/读写飞书文档 |
| `bitable:app` | 创建/读写多维表格 |
| `im:message:send_as_bot` | 机器人发送群消息 |
| `task:task:write` | 创建飞书任务 |
| `drive:drive:readonly` | 读取云盘文件列表 |
| `calendar:calendar:readonly` | 读取日历事件 |
| `im:chat:readonly` | 获取群组列表 |
| `wiki:node:create` | 知识库写入（可选） |

---

## 支持的 LLM 服务商

`LLM_PROVIDER=openai_compatible` 模式支持任何兼容 OpenAI Chat Completions 接口的服务：

- OpenAI（GPT-4o、GPT-4 Turbo）
- DeepSeek（deepseek-chat、deepseek-reasoner）
- 火山方舟 / 豆包
- 通义千问
- 智谱 GLM
- Ollama（本地部署）

飞书 Aily 模式：设置 `LLM_PROVIDER=feishu_aily`，需企业开通飞书 AI 智能伙伴。

---

## 变更日志

### v2.0（当前）
- **多 Agent 架构升级**：依赖感知波次执行，data_analyst → finance_advisor → ceo_assistant 按序推进
- **重试机制**：Agent 级别（3次，0/2/4s退避）+ LLM 调用级别（3次，0/2/4s退避）
- **AutoGen 反思机制**：每个 Agent 输出后自动质量评审，质量问题记录日志
- **上游上下文增强**：下游 Agent 获得完整上游分析（全章节 + 行动项）
- **Agent 提示词全面重写**：7 个 Agent 均升级为专业角色设定（900-1000字系统提示词）
- **前端执行日志重设计**：Agent 活动卡片网格替代终端文字日志
- **飞书上下文智能推荐**：自动读取飞书数据，生成推荐卡片
- **结果页行动项飞书任务**：点击直接创建飞书任务

### v1.0
- 多 Agent 并行执行 MVP
- SSE 实时日志推送
- 飞书文档/多维表/消息发布
