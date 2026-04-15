# 飞书 AI 工作台

> 飞书 AI 挑战赛参赛项目 · 开放创新赛道

面向复杂任务的飞书 AI 工作台：用户描述任务，AI 自动识别类型、调用多 Agent 模块、结果同步飞书。

## 产品定位

当前飞书 CLI/Agent 能力停留在通用性执行——用户给指令，系统执行单一任务。  
用户仍需自己判断：任务类型、应调用哪些工具、需要什么上下文。

**本产品填补这个缺口**：企业在经营分析、立项评估、风险分析、内容规划等复杂任务上的产品化入口。

## 核心流程

```
① 用户描述任务（文字 / 上传文件）
② AI 自动识别任务类型，推荐分析模块
③ 用户确认 / 调整模块组合
④ 多 Agent 并行分析，CEO 助理最后汇总
⑤ 结果同步到飞书（文档 / 多维表格 / 群消息 / 任务）
```

## Agent 模块

| 模块 | 职责 |
|------|------|
| 数据分析师 | 数据趋势、异常、核心指标 |
| 财务顾问 | 收支结构、预算风险 |
| SEO/增长顾问 | 流量分析、内容增长方向 |
| 内容负责人 | 文档写作、知识库整理 |
| 产品经理 | 需求分析、PRD、路线图 |
| 运营负责人 | 行动拆解、任务分配 |
| CEO 助理 | 汇总所有结论，生成管理摘要 |

## 技术架构

```
frontend/   React 18 + TypeScript + Ant Design 5 + Vite
backend/    FastAPI + SQLite + Redis(可选) + lark-oapi
MetaGPT/    多 Agent 协作框架（子模块）
OpenManus/  LLM 工具调用框架（子模块）
```

## 快速开始

```bash
git clone --recurse-submodules https://github.com/shuaigexly/multiagent-lark.git
cd multiagent-lark
```

### 1. 配置环境变量

```bash
cp .env.example backend/.env
# 编辑 backend/.env，填写 OPENAI_API_KEY 和飞书配置
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
cp .env.example .env
npm run dev
```

访问 http://localhost:5173

## 飞书应用权限

在[飞书开放平台](https://open.feishu.cn/)创建应用，配置：

- `docx:document` — 文档读写
- `bitable:app` — 多维表格
- `im:message:send_as_bot` — 发送群消息
- `task:task:write` — 创建任务
- `wiki:node:create` — 知识库（可选）

## 项目结构

```
multiagent-lark/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI 路由（tasks/events/results/feishu）
│   │   ├── agents/       # 7 个分析 Agent + 注册表
│   │   ├── ai/           # MetaGPTEventReporter (v2.1)
│   │   ├── core/         # TaskPlanner, Orchestrator, EventEmitter, DataParser
│   │   ├── feishu/       # lark-oapi 封装（doc/bitable/im/task/wiki）
│   │   └── models/       # SQLAlchemy 数据模型 + Pydantic schemas
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── pages/        # Workbench, ResultView, History
│       ├── components/   # ModuleCard, ExecutionTimeline, FeishuAssetCard
│       └── services/     # API 调用 + 类型定义
├── MetaGPT/              # 子模块：多 Agent SOP 框架
└── OpenManus/            # 子模块：LLM 工具调用框架
```
