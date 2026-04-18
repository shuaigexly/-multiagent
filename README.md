# Puff C21 多 Agent 协同决策工作台

> 飞书 AI 挑战赛参赛项目 · AI 产品赛道项目

<img width="1000" height="400" alt="2465D2A0-C9E1-4E8E-BA3E-625A49B467CF_1_201_a" src="https://github.com/user-attachments/assets/80faa5a3-23f4-4916-b008-c6dfec4d1006" />

---

**Puff! Complex to One，做你的个人协作团队**

基于飞书生态的轻量化多 Agent 协作工具：用户描述任务，AI 自动识别类型、调用多 Agent 模块协同分析、结果实时同步飞书，一键完成流程搭建与任务闭环，填补飞书原生 AI 无法处理复杂协作任务的缺口。



* 差异化定位：区别于飞书现有 AI 仅支持整理消息、添加日历等单一通用型任务，本产品面向经营分析、立项评估、风险分析、内容规划等复杂任务，提供一站式智能协作入口，用户无需自行判断工具与调度流程。
* 核心流程：实现「任务描述 / 文件上传 → AI 自动识别任务类型 → 智能推荐 Agent 组合 → 用户确认调整 → 多 Agent 依赖感知波次执行 → CEO 助理统一汇总 → 结果同步飞书」的全闭环工作流。
* 角色化智能协作：构建数据分析师、财务顾问、产品经理等多角色 Agent 矩阵，支持场景化快速组队与自动组队，模拟真实团队分工协作逻辑。
* 飞书生态深度融合：可读取飞书文档、表格、任务等数据，分析结果一键发布为飞书文档、多维表格、群消息或任务卡片，无缝接入现有工作体系。
* 产品设计：以「Puff机器人」为视觉 IP，采用蓝白清爽风格，突出轻量化、高效率、易上手的产品气质。通过进度条、数据面板等元素，直观体现多 Agent 的工作流与成果，兼具可爱感与专业性，传递「轻盈化解复杂」的产品理念。


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
│   ├── feishu.py     # 飞书数据读写：文档/日历/任务/群聊/发布
│   └── feishu_oauth.py  # 飞书 OAuth2 授权流程（/oauth/url、/oauth/callback、/oauth/status）
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
└── feishu/           # 飞书 SDK 封装
    ├── doc.py        # 富文本文档发布（heading/callout/bullet/divider 结构化块）
    ├── bitable.py    # 多维表格发布（双表：行动清单 + 分析摘要，含单选字段）
    ├── slides.py     # 演示文稿发布（Presentation API + doc 降级兜底）
    ├── reader.py     # 飞书数据读取（云盘/日历/任务/群聊），优先 user_access_token
    ├── task.py       # 创建飞书任务（支持 user_access_token 指定负责人）
    ├── publisher.py  # 统一发布入口（doc/bitable/slides/message）
    └── user_token.py # 用户 OAuth token 内存缓存（user_access_token / open_id）
```

### 前端核心页面

```
frontend/src/
├── pages/
│   ├── Index.tsx           # 工作台主页（任务输入 + 模块选择 + 执行监控）
│   ├── ResultView.tsx      # 结果详情（分节报告 + 行动项 + 飞书发布，支持 slides）
│   ├── FeishuWorkspace.tsx # 飞书工作区（云盘/日历/任务/群聊四 Tab 浏览）
│   ├── Settings.tsx        # 设置页（LLM 配置 + 飞书配置 + OAuth 授权入口）
│   └── History.tsx         # 任务历史列表
├── components/
│   ├── ExecutionTimeline.tsx   # 执行日志（Agent 活动卡片 + 系统事件时间线）
│   ├── ModuleCard.tsx          # Agent 选择卡片（含 persona 信息）
│   ├── ContextSuggestions.tsx  # 飞书上下文智能推荐卡片
│   └── FeishuAssetCard.tsx     # 发布资产卡片（doc/bitable/slides/message）
└── services/
    ├── api.ts      # 后端 API 调用
    ├── feishu.ts   # 飞书数据拉取
    └── config.ts   # 配置读写 + LLM 状态 localStorage 缓存
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
| `task:task:write` | 创建飞书任务（需用户授权） |
| `task:task:readable` | 读取飞书任务列表（需用户授权） |
| `drive:drive:readonly` | 读取云盘文件列表 |
| `calendar:calendar:readonly` | 读取日历事件 |
| `im:chat:readonly` | 获取群组列表 |
| `contact:user.id:readonly` | OAuth 授权后获取用户 open_id |
| `wiki:node:create` | 知识库写入（可选） |

> **注意**：飞书任务 API 需要用户级授权（user_access_token）。在「设置」页面点击「授权飞书任务」完成 OAuth 授权后，才能读取和创建任务。

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

### v3.0（当前）
- **飞书 OAuth 用户授权**：新增完整 OAuth2 流程（`/oauth/url` → 飞书授权 → `/oauth/callback`），user_access_token 持久化存储到数据库，服务重启自动恢复
- **飞书任务用户归属**：创建任务时通过 user_access_token 将任务归属到授权用户，出现在「我负责的」列表
- **飞书上下文自动读取文档内容**：无上传文件时，自动读取飞书上下文中的文档正文（最多 2 篇）作为 Agent 分析数据源
- **云盘/日历使用用户 token**：drive、calendar API 优先使用 user_access_token，提升访问权限覆盖范围
- **群消息发布前置校验**：发布前验证 chat_id 不为空，避免静默失败
- **飞书工作区页面**：新增独立浏览页，支持文档/日历/任务/群聊四 Tab 查看
- **富文本文档发布**：doc.py 升级为结构化块（heading2/3、callout、bullet、divider），不再发布纯文本
- **增强多维表格**：bitable.py 生成双表（行动清单含单选优先级/状态/来源模块字段 + 分析摘要表）
- **演示文稿发布**：新增 slides.py，尝试 Feishu Presentation API，失败自动降级为结构化文档

### v2.0
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
