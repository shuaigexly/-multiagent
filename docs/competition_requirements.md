# 竞赛要求说明文档

> 多维表格上的多智能体虚拟组织（公开版）

---

## 一、竞赛背景与目标

在企业实际运行中，业务的核心并不是单一工具，而是：多个角色围绕数据协作，通过系统推动流程，并基于数据进行持续决策与优化。

飞书多维表格（Base）作为业务系统构建平台，已经具备：
- 灵活的数据结构与关系建模能力
- 自动化流程与权限控制能力
- 可视化分析与协作能力

本次竞赛聚焦于：**构建一个由 Agent 员工组成的虚拟组织**，这些 Agent 作为"数字员工"，通过多维表格 OpenAPI 协同工作，完成系统搭建、业务运行与数据分析。

---

## 二、核心任务

参赛团队需完成一个虚拟员工系统的构建与运行：

- 多个 AI Agent 扮演不同业务角色（员工）
- 所有业务通过飞书多维表格（Base）进行数据沉淀与状态管理
- Agent 通过飞书和多维表格 OpenAPI 操作多维表格，实现协同工作
- 系统能够持续运行并生成数据
- 最终基于数据完成分析、报告或决策输出

---

## 三、系统能力要求

### REQ-1：虚拟员工建模

**要求：**
- 至少定义 **3 个及以上角色**（Agent）
- 每个 Agent 对应一个"员工角色"

**必须包含：**
- 角色职责定义
- 输入 / 输出说明
- 角色间协作关系

**本项目实现（7个角色）：**

| 角色 | Agent ID | 职责 | 执行波次 |
|------|----------|------|----------|
| 数据分析师 | `data_analyst` | 指标拆解、趋势洞察、异常归因 | Wave 1（并行） |
| 内容负责人 | `content_manager` | 内容资产盘点、创作策略 | Wave 1（并行） |
| SEO 顾问 | `seo_advisor` | 关键词机会、流量增长路径 | Wave 1（并行） |
| 产品经理 | `product_manager` | 需求分析、路线图规划 | Wave 1（并行） |
| 运营负责人 | `operations_manager` | 执行规划、任务拆解 | Wave 1（并行） |
| 财务顾问 | `finance_advisor` | 收支诊断、现金流分析 | Wave 2（依赖数据分析师） |
| CEO 助理 | `ceo_assistant` | 跨职能整合、管理决策摘要 | Wave 3（汇总所有上游） |

---

### REQ-2：业务系统构建

**必须实现：**
- 数据表设计（实体建模）
- 字段设计（结构化表达）
- **表间关系（关联记录）**
- 状态字段（流程驱动）

**技术要求：** 必须让 Agent 角色通过**多维表格 OpenAPI / SDK / CLI** 操作数据。

**本项目实现（4张表）：**

| 表格 | 用途 | 关联关系 |
|------|------|----------|
| 分析任务 | 主表，状态机驱动 | 无（主表） |
| 岗位分析 | 每岗 Agent 输出（6条/任务） | ←「关联任务」字段（type=18）关联主表 |
| 综合报告 | CEO 助理综合决策报告 | ←「关联任务」字段（type=18）关联主表 |
| 数字员工效能 | 各岗位处理任务数统计 | 无 |

状态机流转：`待分析 → 分析中 → 已完成 → 已归档`

---

### REQ-3：业务运行与协同

**必须形成完整链路：**

```
数据产生 → 状态更新 → Agent处理 → 决策 → 反馈 → 再流转
```

**本项目实现：**

```
写入种子任务（待分析）
       │
       ▼
调度器领取 → 标记「分析中」
       │
       ▼
Wave 1: 5个 Agent 并行分析
       │
       ▼
Wave 2: 财务顾问（依赖数据分析师输出）
       │
       ▼
Wave 3: CEO 助理（汇总全部上游输出）
       │
  ┌────┴────────────────────┐
  ▼                         ▼
写入岗位分析表           写入综合报告表
（含关联字段）           （含关联字段）
                             │
                             ▼
                    CEO 行动项 → 自动生成新的「待分析」任务
                             │         （再流转闭环）
                             ▼
                          已完成 + 飞书消息通知
```

---

### REQ-4：数据分析与报告

**必须实现：**
- 基于业务数据的自动分析（LLM 或逻辑计算）
- 输出至少一种结果形式（周报 / 数据洞察 / 决策建议）
- **由 Agent 员工通过飞书发送**

**本项目实现：**
- 7 岗 LLM 联合分析，CEO 助理生成综合决策报告
- 报告写入「综合报告」多维表格（含核心结论、重要机会、重要风险、CEO决策事项）
- 任务完成后自动向飞书群推送 CEO 报告摘要卡片消息（`im.py`）

---

## 四、参赛约束（违规一票否决）

### 4.1 模型限制

- ✅ **必须使用国内模型**
- ❌ 禁止使用 OpenAI、Anthropic Claude、Google Gemini 等境外模型
- ❌ 禁止对模型进行任何形式的微调（全量微调、LoRA、PEFT、RLHF 等）
- ✅ 允许：RAG、Prompt Engineering、Tool-use 编排

**本项目默认模型：** `deepseek-chat`（DeepSeek，国内）

支持的国内模型：

| 服务商 | 模型 | 配置方式 |
|--------|------|----------|
| DeepSeek（默认） | `deepseek-chat` | `LLM_BASE_URL=https://api.deepseek.com/v1` |
| 通义千问 | `qwen-plus` | `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 智谱 GLM | `glm-4-flash` | `LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4` |
| 火山方舟·豆包 | `doubao-pro-32k` | `LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3` |
| 飞书 Aily | — | `LLM_PROVIDER=feishu_aily` + `AILY_APP_ID=...` |

### 4.2 复现与反作弊

- ✅ 所有系统搭建必须通过真实 CLI/SDK/API 完成
- ❌ 严禁 Mock 任何功能、伪造日志、虚构结果
- 评测端将通过**行为回放与动态探测**进行交叉验证

---

## 五、交付物清单

| 交付物 | 状态 | 说明 |
|--------|------|------|
| 源代码 | ✅ | 完整可运行，含清晰注释 |
| 可运行包 | ✅ | `docker-compose.yml` 一键启动 |
| 技术文档 | ✅ | `README.md` + 本文档 |
| 测试报告 | ✅ | `backend/tests/` pytest 测试套件 |
| 演示材料 | 待补充 | PPT / 演示视频 |
| 多维表格产物链接 | 待补充 | 实际运行后提供可访问链接 |

---

## 六、运行验证

```bash
# 1. 配置环境变量
cp backend/.env.example backend/.env
# 填入 DeepSeek API Key 和飞书应用凭证

# 2. 启动服务
docker-compose up

# 3. 初始化多维表格（创建4张表 + 写入种子任务）
curl -X POST http://localhost:8000/api/v1/workflow/setup \
  -H "Content-Type: application/json" \
  -d '{"name": "内容运营虚拟组织"}'

# 4. 启动七岗调度循环
curl -X POST http://localhost:8000/api/v1/workflow/start \
  -H "Content-Type: application/json" \
  -d '{"app_token": "<上一步返回的app_token>", "table_ids": {...}}'

# 5. 运行测试
cd backend && pytest tests/ -v
```
