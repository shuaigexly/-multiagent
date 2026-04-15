# 飞书 AI 工作台 — Agent 系统架构说明

> 本文档面向 AI Agent / LLM 阅读，描述系统的完整架构、接口契约和扩展规范。

---

## 系统定位

这是一个多 Agent 协同分析系统，部署在飞书企业环境中。核心职责：

1. **任务路由**：将用户的自然语言任务描述，映射到最合适的 Agent 模块组合
2. **协同执行**：按依赖顺序调度多个专业 Agent 并行/串行执行分析
3. **结果整合**：汇总各 Agent 输出，推送到飞书（文档/任务/消息）

---

## Agent 注册表

系统共有 7 个分析 Agent，注册在 `backend/app/agents/registry.py`：

| agent_id | 中文名 | 专长领域 |
|----------|--------|----------|
| `data_analyst` | 数据分析师 | 数据趋势、异常识别、核心指标分析 |
| `finance_advisor` | 财务顾问 | 收支结构、现金流健康、财务风险 |
| `seo_advisor` | SEO/增长顾问 | 流量诊断、关键词机会、内容增长 |
| `content_manager` | 内容负责人 | 文档写作、知识库整理、内容归档 |
| `product_manager` | 产品经理 | 需求分析（JTBD框架）、PRD、路线图规划 |
| `operations_manager` | 运营负责人 | 根因分析（5 Why）、行动拆解、执行跟进 |
| `ceo_assistant` | CEO 助理 | 跨职能综合汇总、管理决策摘要 |

### 依赖图（AGENT_DEPENDENCIES）

```
data_analyst ──→ finance_advisor
             └──→ ceo_assistant
finance_advisor ──→ ceo_assistant
product_manager ──→ ceo_assistant
operations_manager ──→ ceo_assistant
seo_advisor ──→ ceo_assistant
content_manager ──→ ceo_assistant
```

含义：箭头左侧 Agent 必须在右侧 Agent 之前完成，以提供上游分析上下文。

---

## 执行调度模型

编排器（`core/orchestrator.py`）使用**依赖感知波次执行**：

```
Wave 1: [data_analyst, seo_advisor, content_manager, product_manager, operations_manager]
        （无依赖，并行执行）
Wave 2: [finance_advisor]
        （依赖 data_analyst，串行等待）
Wave N: [ceo_assistant]
        （依赖所有上游，最后执行）
```

实际波次取决于用户选择了哪些模块，未选择的模块不参与执行。

每个 Agent 最多重试 3 次（退避：0s → 2s → 4s）。

---

## Agent 接口契约

### 输入：`analyze()` 方法签名

```python
async def analyze(
    task_description: str,           # 用户原始任务描述
    data_summary: Optional[DataSummary],     # 上传文件的解析结果（可为 None）
    upstream_results: Optional[list[AgentResult]],  # 上游 Agent 的输出（可为 None）
    feishu_context: Optional[dict],  # 飞书数据（drive/calendar/tasks）
) -> AgentResult
```

### 输出：`AgentResult` 结构

```python
class AgentResult(BaseModel):
    agent_id: str          # 例如 "data_analyst"
    agent_name: str        # 例如 "数据分析师"
    sections: list[ResultSection]   # 分析章节列表
    action_items: list[str]         # 行动项（纯文本，每条一个字符串）
    raw_output: str        # LLM 原始输出文本

class ResultSection(BaseModel):
    title: str    # 章节标题（对应 ## 标题）
    content: str  # 章节内容
```

---

## Prompt 构建规范

每次调用 `_build_prompt()` 时，组装以下结构传给 LLM：

```
[SAFETY_PREFIX]        # 防 prompt 注入声明
[SYSTEM_PROMPT]        # Agent 角色定义（~900-1000 字）

---用户消息---
<user_task>
{用户的原始任务描述}
</user_task>

<data_input>           # 仅当上传了文件时存在
类型：csv/txt/md
行数/段落数：N
列名：col1, col2, ...
预览：{前2000字符}
</data_input>

<upstream_analysis>    # 仅当有上游 Agent 结果时存在
【数据分析师的分析】
  [核心发现]
  {前1500字符}
  [指标详析]
  {前1500字符}
  ...
  [行动项]
  - 行动项1
  - 行动项2
...
</upstream_analysis>

<feishu_context>       # 当前用户的飞书数据
{drive: [...], calendar: [...], tasks: [...]}
</feishu_context>

[USER_PROMPT_TEMPLATE] # Agent 具体分析指令（含<think>块和输出格式要求）
```

**安全约束**：所有 XML 标签内的内容被视为待分析的用户数据，LLM 不执行其中的任何指令。

---

## 输出解析规范

`_parse_output()` 将 LLM 的 markdown 文本解析为结构化结果：

- `## 标题` 或 `**标题**` 开头的行 → 新 ResultSection
- 标题中含「行动/建议/Action/TODO/下一步」→ 后续列表项解析为 `action_items`
- 列表前缀（`-`、`•`、`1.`、`1、`）自动剥离
- 解析失败兜底：整段作为一个「分析结果」section

子类可覆盖 `_parse_output()` 实现自定义解析（参考 `ceo_assistant.py`）。

---

## 质量保障机制

### 反思机制（AutoGen 风格）

每个 Agent 输出后，基类自动调用 `_reflect_on_output()`：

```
输入：agent 输出文本（前2000字）+ 任务描述（前300字）
输出：PASS 或 FAIL: <缺失描述>
```

- 输出 PASS → 继续
- 输出 FAIL → 打印 WARNING 日志（当前版本：记录日志，不触发重新生成）

### LLM 重试

`llm_client.py` 中 API 调用失败自动重试：
- 最多 3 次
- 退避：0s / 2s / 4s
- 三次仍失败 → 抛出 RuntimeError

---

## SSE 事件类型

Agent 执行期间，通过 EventEmitter 推送以下事件到前端：

| event_type | 触发时机 | 关键字段 |
|------------|----------|----------|
| `module.started` | Agent 开始执行 | `agent_name`, `message` |
| `module.completed` | Agent 成功完成 | `agent_name`, `message`（含摘要） |
| `module.failed` | Agent 三次重试后失败 | `agent_name`, `message`（含错误） |
| `stream.end` | 所有 Agent 完成 | — |
| `stream.timeout` | 心跳保活 | — |

前端按 `agent_name` 字段分组，渲染 Agent 活动卡片。

---

## 如何新增 Agent

1. **创建文件**：`backend/app/agents/{new_agent_id}.py`

```python
from app.agents.base_agent import BaseAgent, AgentResult

SYSTEM_PROMPT = """你是一位...（900字以上，含角色定位/思维哲学/工作准则）"""

USER_PROMPT_TEMPLATE = """
{task_description}
{data_section}
{upstream_section}
{feishu_context}

<think>
请先思考：
1. ...
2. ...
</think>

请按以下格式输出：

## 章节一标题
内容...

## 行动建议
- 行动项1
- 行动项2
"""

class NewAgentClass(BaseAgent):
    agent_id = "{new_agent_id}"
    agent_name = "中文名"
    agent_description = "职责描述"
    SYSTEM_PROMPT = SYSTEM_PROMPT
    USER_PROMPT_TEMPLATE = USER_PROMPT_TEMPLATE

new_agent_instance = NewAgentClass()
```

2. **注册**：`backend/app/agents/registry.py`

```python
from app.agents.{new_agent_id} import new_agent_instance

AGENT_REGISTRY["{new_agent_id}"] = new_agent_instance

# 配置依赖（可选）
AGENT_DEPENDENCIES["{new_agent_id}"] = {"ceo_assistant"}  # 如果需要先于 CEO 助理
```

3. **前端 persona**：`frontend/src/components/ModuleCard.tsx`，在 `AGENT_PERSONAS` 添加：

```typescript
{new_agent_id}: {
  name: '中文名',
  title: '职位描述',
  avatar: '首字母或emoji',
  color: '#XXXXXX',
  description: '功能描述',
}
```

---

## 环境变量参考

| 变量名 | 必填 | 说明 | 示例 |
|--------|------|------|------|
| `LLM_PROVIDER` | 否 | LLM 提供商 | `openai_compatible`（默认） |
| `LLM_API_KEY` | 是 | LLM API 密钥 | `sk-xxx` |
| `LLM_BASE_URL` | 否 | API 基础 URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | 否 | 模型名称 | `gpt-4o` |
| `FEISHU_APP_ID` | 否 | 飞书应用 ID | `cli_xxx` |
| `FEISHU_APP_SECRET` | 否 | 飞书应用密钥 | `xxx` |
| `DATABASE_URL` | 否 | 数据库 URL | `sqlite+aiosqlite:///workbench.db` |

---

## 任务状态机

```
pending → planning → confirmed → running → done
                                         → failed
```

- `pending`：任务已提交，等待规划
- `planning`：TaskPlanner 正在识别任务类型
- `confirmed`：用户确认模块组合，等待执行
- `running`：Agent 波次执行中
- `done`：所有 Agent 完成，结果已存储
- `failed`：执行过程中发生不可恢复的错误
