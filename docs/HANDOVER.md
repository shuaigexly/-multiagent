# 技术交接文档

> 面向：新接手开发者 / 协作者  
> 最后更新：2026年

---

## 一、项目概览

这是一个飞书 AI 工作台，核心是多 Agent 协同分析系统。用户输入任务描述，系统自动选择合适的 AI 专家模块组合，协同分析后将结果同步到飞书（文档/任务/消息）。

**技术栈**
- 后端：Python 3.11+ / FastAPI / SQLite / asyncio
- 前端：React 18 / TypeScript / Tailwind CSS / shadcn/ui
- 飞书集成：lark-oapi SDK
- LLM：支持 OpenAI 兼容接口（含 DeepSeek、豆包等）或飞书 Aily

---

## 二、本地运行

```bash
# 后端（新开终端）
cd backend
pip install -r requirements.txt
cp .env.example .env   # 填写 LLM_API_KEY + FEISHU_APP_ID + FEISHU_APP_SECRET
uvicorn app.main:app --reload --port 8000

# 前端（新开终端）
cd frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env
npm run dev
# 访问 http://localhost:5173
```

**最低配置**（飞书未配置也能跑，只是没有飞书功能）：
```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

### Docker 部署

- 已提供 `backend/Dockerfile`、`frontend/Dockerfile`、`docker-compose.yml`。
- 首次部署先手动创建 `backend/.env`，可从 `backend/.env.example` 复制后修改。
- 建议在 `backend/.env` 中保留 SQLite，并使用 `DATABASE_URL=sqlite+aiosqlite:///./data/workbench.db`。
- 启动命令：`docker compose up --build -d`。
- 后端默认映射到 `http://localhost:8000`，前端映射到 `http://localhost:5173`。
- SQLite 数据目录挂载到仓库根目录 `data/`，上传文件挂载到 `uploads/`。
- `redis` 服务已在 compose 中提供；当前为可选，不依赖它也可运行主流程。
- 停止命令：`docker compose down`。

---

## 三、完整请求链路

```
用户提交任务
  │
  ▼
POST /api/v1/tasks
  → task_planner.plan_task()       # LLM 识别任务类型，推荐模块列表
  → 返回 task_id + selected_modules（前端展示，用户可调整）
  │
  ▼
POST /api/v1/tasks/{id}/confirm    # 用户确认模块组合
  → orchestrate() 异步启动
  │
  ▼
GET /api/v1/tasks/{id}/stream      # SSE 长连接，实时推送执行日志
  │
  ├── [可选] _enrich_from_feishu_context()  # 无上传文件时，自动读取飞书文档内容作为分析数据
  ├── 波次1：data_analyst（无依赖）并行启动
  ├── 波次2：finance_advisor（依赖data_analyst完成）
  ├── 波次N：其他无依赖模块并行运行
  └── 最终波：ceo_assistant（汇总所有上游结果）
  │
  ▼
GET /api/v1/tasks/{id}/results     # 获取完整分析报告
POST /api/v1/feishu/publish        # 发布到飞书（文档/多维表格/演示文稿/消息）
```

**飞书 OAuth 授权流程**（用于任务 API 用户级访问）：
```
GET /api/v1/feishu/oauth/url       # 生成飞书授权链接
  → 用户在飞书完成授权
GET /api/v1/feishu/oauth/callback  # 接收 code，交换 user_access_token
  → 存入数据库 + 更新内存缓存
GET /api/v1/feishu/oauth/status    # 查询当前授权状态
```

---

## 四、核心模块详解

### 4.1 任务规划器（`core/task_planner.py`）

- 用 LLM 分析用户输入，判断任务类型（8种），推荐 2-4 个 Agent 模块
- 有关键词匹配降级逻辑（LLM 不可用时自动切换）
- 强制规则：数据类任务必须包含 data_analyst（放最前），汇总类必须包含 ceo_assistant（放最后）

### 4.2 编排器（`core/orchestrator.py`）

核心算法是**依赖感知波次执行**：

```python
# 伪代码
while 还有未完成的 agent:
    ready = [agent for agent if agent的所有依赖都已完成]
    # 在 ready 里，SEQUENTIAL_LAST（ceo_assistant）最后处理
    并行执行 ready 中所有 agent
    将结果加入 all_results
    标记为已完成
```

每个 Agent 有 3 次重试机会（0s/2s/4s 退避）。

### 4.3 Agent 基类（`agents/base_agent.py`）

每个 Agent 执行三步：
1. `_build_prompt()` — 组装 prompt（任务描述 + 文件数据 + 上游结果 + 飞书上下文）
2. `_call_llm()` — 调用 LLM（含 SAFETY_PREFIX 防注入）
3. `_reflect_on_output()` — 质量审查（输出不合格打 WARNING 日志）
4. `_parse_output()` — 解析输出为结构化 AgentResult

### 4.4 LLM 客户端（`core/llm_client.py`）

- 支持 `openai_compatible`（默认）和 `feishu_aily` 两种模式
- openai_compatible 自动重试 3 次（0s/2s/4s 退避）
- 通过环境变量 `LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL` 配置

### 4.5 Agent 依赖图（`agents/registry.py`）

```python
AGENT_DEPENDENCIES = {
    "data_analyst":       {"finance_advisor", "ceo_assistant"},  # data_analyst 先于这些
    "finance_advisor":    {"ceo_assistant"},
    "product_manager":    {"ceo_assistant"},
    "operations_manager": {"ceo_assistant"},
    "seo_advisor":        {"ceo_assistant"},
    "content_manager":    {"ceo_assistant"},
}
# 含义：key 必须在 value 中的所有 agent 之前完成
```

新增 Agent 时，在这里配置依赖关系即可，orchestrator 自动处理。

### 4.6 SSE 事件系统（`core/event_emitter.py`）

所有 Agent 状态变化通过 EventEmitter 推送 SSE 事件：
- `module.started` — Agent 开始执行
- `module.completed` — Agent 完成
- `module.failed` — Agent 失败
- `stream.end` — 所有 Agent 完成

前端 `ExecutionTimeline.tsx` 按 `agent_name` 字段分组，渲染成卡片。

---

## 五、Agent 提示词规范

每个 Agent 有两段提示词：

**SYSTEM_PROMPT（约 900-1000 字）**
- 角色定位（头衔、年资、专长领域）
- 思维哲学（3-5 条核心原则）
- 工作准则（如何对待数据、如何标注估算/假设）
- 飞书上下文使用方式

**USER_PROMPT_TEMPLATE（约 600-900 字）**
- `{task_description}` — 用户任务（XML 标签包裹）
- `{data_section}` — 上传文件数据（可选）
- `{upstream_section}` — 上游 Agent 结果（可选）
- `{feishu_context}` — 飞书数据（文档/日历/任务）
- `<think>` 块 — 引导 Agent 分步推理
- 强制输出章节（## 标题格式）

添加新 Agent 步骤：
1. 复制 `agents/data_analyst.py` 为模板
2. 修改 `agent_id / agent_name / agent_description`
3. 重写 `SYSTEM_PROMPT` 和 `USER_PROMPT_TEMPLATE`
4. 在 `agents/registry.py` 注册 + 配置依赖
5. 在前端 `components/ModuleCard.tsx` 的 `AGENT_PERSONAS` 添加 persona 信息

---

## 六、飞书集成

飞书功能需要企业自建应用，配置 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`：

| 功能 | 后端路由 | 飞书权限 | 备注 |
|------|----------|----------|------|
| 读取云盘文件 | GET /api/v1/feishu/drive | drive:drive:readonly | 优先用 user_access_token |
| 读取日历事件 | GET /api/v1/feishu/calendar | calendar:calendar:readonly | 优先用 user_access_token |
| 读取待办任务 | GET /api/v1/feishu/tasks | task:task:readable | **必须** user_access_token |
| 读取群组列表 | GET /api/v1/feishu/chats | im:chat:readonly | — |
| 创建飞书任务 | POST /api/v1/feishu/tasks | task:task:write | 优先用 user_access_token（任务归属用户） |
| 发布文档 | POST /api/v1/feishu/publish | docx:document | 富文本结构化块 |
| 发布多维表格 | POST /api/v1/feishu/publish | bitable:app | 双表+单选字段 |
| 发布演示文稿 | POST /api/v1/feishu/publish | — | 尝试 Presentation API，失败降级为 doc |
| 发布群消息/卡片 | POST /api/v1/feishu/publish | im:message:send_as_bot | 有 chat_id 发群消息；无 chat_id 且已 OAuth 则发私信（DM 兜底） |
| OAuth 授权 | GET /api/v1/feishu/oauth/url | contact:user.id:readonly | 跳转飞书授权页面 |
| **Bot 事件回调** | POST /api/v1/feishu/bot/event | im:message.receive_v1 | @机器人触发多 Agent 分析，原线程回复 |

### DM 兜底机制

发布「群消息」或「互动卡片」时，若未填写群 ID：

- 已完成飞书 OAuth 授权 → 自动改为发**私信**给已授权用户
- 未授权 → 返回 400 错误，提示先授权或填写群 ID

前端发布页检测 OAuth 状态（`/api/v1/feishu/oauth/status`），已授权时展示提示"将通过私信发给已授权用户"，并放开发布按钮。

### Bot 事件订阅

在飞书群里 @ 机器人（或直接私聊），触发完整多 Agent 分析并在原线程回复结果。

**配置步骤**：
1. 飞书开放平台 → 事件订阅 → 填入回调地址：`{VITE_API_URL}/api/v1/feishu/bot/event`
2. 订阅事件：`im.message.receive_v1`
3. 复制 Verification Token → 粘贴到工作台「设置」页 Bot 配置区
4. 如启用加密，同步填写 Encrypt Key

**设计要点**：
- 3 秒内返回 200（challenge 验证即时响应，实际任务放 BackgroundTask）
- `feishu_bot_events` 表以 `event_id` 为主键，自动幂等去重
- 发送方为机器人（`sender_type != user`）时自动过滤，防自回环
- 完成后回复包含完整报告链接：`{FRONTEND_BASE_URL}/results/{task_id}`

### 飞书任务 API 说明

飞书任务 v2 API 必须使用 `user_access_token`（tenant_access_token 被拒绝）。完整流程：
1. 用户在「设置」页面点击「授权飞书任务」
2. 后端生成 OAuth 链接，用户跳转到飞书完成授权
3. 飞书回调到 `/api/v1/feishu/oauth/callback`，后端用 code 换取 user_access_token
4. Token 存入数据库，服务重启自动恢复（`_load_runtime_config`）
5. Token 过期时（code=99991668）自动清除，需重新授权

未配置飞书时，以上接口会返回空数据，不影响主流程。

---

## 七、数据库

使用 SQLite（`backend/workbench.db`），四张表：
- `tasks` — 任务记录（id, description, status, selected_modules, created_at）
- `agent_results` — Agent 输出（task_id, agent_id, sections JSON, action_items JSON）
- `user_config` — 运行时配置（key/value，包含 LLM 配置、飞书凭证、用户 OAuth token）
- `feishu_bot_events` — Bot 事件幂等表（event_id PK, task_id, status, source_message_id）

通过 SQLAlchemy async ORM 操作，无需手动建表（startup 自动 create_all）。

**user_config 关键字段**：

| key | 说明 |
|-----|------|
| `llm_api_key` / `llm_model` | LLM 配置 |
| `feishu_app_id` / `feishu_app_secret` | 飞书应用凭证 |
| `feishu_user_access_token` | 用户 OAuth token（飞书任务 API 必须） |
| `feishu_user_refresh_token` | 用户 refresh token |
| `feishu_user_open_id` | 用户 open_id（创建任务时用于指定负责人；无 chat_id 时作为 DM 兜底目标） |
| `feishu_bot_verification_token` | Bot 事件回调验证 token |
| `feishu_bot_encrypt_key` | Bot 事件回调加密密钥（可选） |

---

## 八、常见问题

**Q: LLM 调用超时怎么办？**  
A: `llm_client.py` 已内置 3 次重试，每次超时后等待 0/2/4s。如需调整超时时间，在 `AsyncOpenAI()` 构造时加 `timeout=60`。

**Q: 某个 Agent 一直失败？**  
A: 查看后端日志，搜索 `Agent {agent_id} failed`，查看具体错误。Agent 最多重试 3 次，失败后返回降级结果（而非静默跳过），不会中断整个任务。

**Q: 飞书上下文不显示？**  
A: 检查 `.env` 中 `FEISHU_APP_ID / FEISHU_APP_SECRET` 是否正确，以及飞书应用是否已发布上线（自建应用需要发布才能生效）。

**Q: 飞书任务读取/创建失败？**  
A: 飞书任务 v2 API 强制要求 user_access_token。在「设置」页面点击「授权飞书任务」完成 OAuth 授权。Token 过期时（日志中出现 code=99991668）需重新授权。

**Q: 发布群消息/卡片报错"需要提供 chat_id"？**  
A: 两种解决方式：①在发布面板填写目标群 ID（可在飞书群聊 → 群设置中复制）；②在「设置」页面完成飞书 OAuth 授权，系统会自动改为发私信给已授权用户（DM 兜底）。

**Q: 如何切换 LLM 到 DeepSeek？**  
```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

**Q: 前端 Agent 卡片名字对不上？**  
A: 检查 `frontend/src/components/ExecutionTimeline.tsx` 中的 `PERSONA_ALIASES`，后端 Agent 返回的 `agent_name` 需要在别名列表中。

---

## 九、扩展方向

- **新增 Agent**：参考上方「Agent 提示词规范」章节
- **新增任务类型**：在 `core/task_planner.py` 的 `TASK_TYPES` 字典添加
- **更换 LLM**：修改 `.env` 环境变量即可，无需改代码
- **飞书发布格式**：`feishu/` 目录下各文件控制发布到不同飞书产品的格式
- **AFlow 工作流优化**（高级）：参考 MetaGPT AFlow 论文，用 MCTS 搜索最优 Agent 组合和顺序
