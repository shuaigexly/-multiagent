# 技术交接文档

> 面向：新接手开发者 / 协作者  
> 最后更新：2025年

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
  ├── 波次1：data_analyst（无依赖）并行启动
  ├── 波次2：finance_advisor（依赖data_analyst完成）
  ├── 波次N：其他无依赖模块并行运行
  └── 最终波：ceo_assistant（汇总所有上游结果）
  │
  ▼
GET /api/v1/tasks/{id}/results     # 获取完整分析报告
POST /api/v1/feishu/publish        # 发布到飞书（文档/多维表/消息）
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

| 功能 | 后端路由 | 飞书权限 |
|------|----------|----------|
| 读取云盘文件 | GET /api/v1/feishu/drive | drive:drive:readonly |
| 读取日历事件 | GET /api/v1/feishu/calendar | calendar:calendar:readonly |
| 读取待办任务 | GET /api/v1/feishu/tasks | task:task:readonly |
| 读取群组列表 | GET /api/v1/feishu/chats | im:chat:readonly |
| 创建飞书任务 | POST /api/v1/feishu/tasks | task:task:write |
| 发布结果 | POST /api/v1/feishu/publish | docx:document + im:message |

未配置飞书时，以上接口会返回空数据，不影响主流程。

---

## 七、数据库

使用 SQLite（`backend/workbench.db`），两张表：
- `tasks` — 任务记录（id, description, status, selected_modules, created_at）
- `agent_results` — Agent 输出（task_id, agent_id, sections JSON, action_items JSON）

通过 SQLAlchemy async ORM 操作，无需手动建表（startup 自动 create_all）。

---

## 八、常见问题

**Q: LLM 调用超时怎么办？**  
A: `llm_client.py` 已内置 3 次重试，每次超时后等待 0/2/4s。如需调整超时时间，在 `AsyncOpenAI()` 构造时加 `timeout=60`。

**Q: 某个 Agent 一直失败？**  
A: 查看后端日志，搜索 `Agent {agent_id} failed`，查看具体错误。Agent 最多重试 3 次，失败后跳过继续执行其他 Agent，不会中断整个任务。

**Q: 飞书上下文不显示？**  
A: 检查 `.env` 中 `FEISHU_APP_ID / FEISHU_APP_SECRET` 是否正确，以及飞书应用是否已发布上线（自建应用需要发布才能生效）。

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
