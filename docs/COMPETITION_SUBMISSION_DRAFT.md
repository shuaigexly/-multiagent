# 飞书 AI 校园挑战赛 · 复赛作品提交稿

> **项目名称**：Puff C21 · 多维表格上的多智能体虚拟组织
> **赛道**：AI 产品赛道
> **代码仓库**：https://github.com/shuaigexly/-multiagent
> **最新可访问 Bitable Demo**：https://feishu.cn/base/T2QibqZe5aZa6mseY1UcF5A0n1f （v8.6.20-r51 实跑，含 r28-r49 全量特性）
> **历史 Bitable Demo**：https://feishu.cn/base/GXkTbYLn9a3WRbswJ99crIcMnvh （v8.6.20-r25 实跑，对比基线）
> **GitHub Pages 插件入口**：https://shuaigexly.github.io/-multiagent/bitable.html

---

## 一、个人信息

> ⚠️ 请在提交前填写以下空白字段。

### 个人参赛 / 小组参赛

| 姓名   | 角色            | 项目中负责的工作简述                                                                                                          | 学校                  | 专业                       | 学历   | 毕业时间  | 实习地点         | 最快到岗 | 可实习时长 |
| ------ | --------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------- | -------------------------- | ------ | --------- | ---------------- | -------- | ---------- |
| 徐砻毓 | 组长 / 全栈开发 | 7 岗 Agent DAG 设计与实现、Bitable 12 表 + 24 视图自动建模、SSE 实时推送、Round-10/11 安全审计、飞书插件部署、端到端 E2E 测试 | EDHEC Business School | _管理学和国际金融学双学位_ | _硕士_ | _2026.12_ | _上海/深圳/北京_ | _ASAP_   | _3-6个月_  |

---

## 二、项目结果展示

### 1. 总项目结果展示

#### 1）Demo 展示

**🎬 实跑录屏建议路径（5 月 7 日提交前完成）**

操作步骤：

1. 打开飞书插件入口（GitHub Pages 部署）→ 自动 OAuth 进入 Bitable
2. 在「分析任务」表写入一条任务（标题 / 背景 / 数据源 CSV）
3. 调度器 30s 内领取 → 7 岗 DAG 自动并行 + 依赖排序执行
4. 实时观察前端 SSE 进度条（Wave1 → Wave2 → Wave3）
5. CEO 助理汇总报告写回「综合报告」表 → 飞书群收到富文本卡片
6. CEO 行动项自动生成新「待分析」任务 → 形成业务闭环

**已运行交付物**

##### v8.6.20-r51 最新实跑（含 r28-r49 全量特性 / 2026-05-01）

- 🆔 app_token：`T2QibqZe5aZa6mseY1UcF5A0n1f`
- 🔗 Bitable URL：https://feishu.cn/base/T2QibqZe5aZa6mseY1UcF5A0n1f
- ⏱️ 端到端耗时：3014.5 s（≈50 min，含 setup + cycle + audit）
- ✅ verify_bitable issues：**0**
- 📊 cycle 处理任务数 = 3，状态分布 `{已归档: 1, 已完成: 3, 待分析: 15}`，CEO 示例报告：「InsightHub 三月运营复盘 健康=🟡 关注 紧急度=4」
- 📊 落库数据：12 张表（task / output / report / performance / datasource / evidence / review / action / review_history / archive / automation_log / template）/ ~24 视图 / 业务闭环（CEO 行动项 → follow-up + review_recheck 自动跟进任务都生效）/ 65 条自动化日志

##### v8.6.20-r25 历史实跑（对比基线 / 2026-04-30）

- 🆔 app_token：`GXkTbYLn9a3WRbswJ99crIcMnvh`
- 🔗 Bitable URL：https://feishu.cn/base/GXkTbYLn9a3WRbswJ99crIcMnvh
- ⏱️ 端到端耗时：3153.9 s（≈52 min）
- ✅ verify_bitable issues：**0**
- 📊 落库数据：12 张表 / 24 视图 / 20 任务 / 21 岗位输出 / 35 证据链 / 66 自动化日志

> 两次端到端实跑 verify issues 都是 0，说明 r28-r49 累积的 22 轮迭代没有引入新 Bitable 落库 bug。

#### 2）核心部分代码展示

**七岗 DAG 拓扑排序核心**：[`backend/app/bitable_workflow/registry.py`](../backend/app/bitable_workflow/registry.py)

```python
AGENT_DEPENDENCIES = {
    "data_analyst": [],
    "content_manager": [],
    "seo_advisor": [],
    "product_manager": [],
    "operations_manager": [],
    "finance_advisor": ["data_analyst"],          # Wave2 依赖
    "ceo_assistant": ["data_analyst", "content_manager", "seo_advisor",
                      "product_manager", "operations_manager", "finance_advisor"],
}
# 调度器据此 DAG 拓扑排序自动分波次并行
```

**Bitable 真实 API 调用 + 重试 + 限流**：[`backend/app/bitable_workflow/bitable_ops.py`](../backend/app/bitable_workflow/bitable_ops.py)

```python
async def search_records(app_token, table_id, *, filter_conditions=None,
                         sort=None, automatic_fields=False, ...) -> list[dict]:
    """飞书原生 records/search API，支持过滤+排序+自动字段+完整分页 has_more。
    automatic_fields 错误码 1254000/1254001 自动剥离重试；5xx 走 with_retry。"""
    ...
```

**业务闭环：CEO 行动项 → 写回主表生成新任务**：[`backend/app/bitable_workflow/scheduler.py`](../backend/app/bitable_workflow/scheduler.py)

```python
async def _create_followup_tasks(app_token, task_tid, ceo_result):
    actions = _extract_top_actions(ceo_result, max_count=3)
    for action in actions:
        if action.title.startswith("[跟进]"):  # 防无限循环
            continue
        await bitable_ops.create_record(app_token, task_tid, fields={
            "任务标题": f"[跟进] {action.title}",
            "状态": "待分析",
            ...  # 调度循环下一轮自动接手
        })
```

**真实 LLM 调用（无 Mock）**：[`backend/app/agents/llm_client.py`](../backend/app/agents/llm_client.py)

```python
# 默认 deepseek-chat / 智谱 GLM / 火山引擎，禁用 Claude/GPT
DEFAULT_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
DEFAULT_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
```

#### 3）项目亮点介绍

**亮点 1：飞书 Bitable 原生交付（不是套壳，是真原生）**

- 12 张表 / 24 视图 / 5 看板 / 1 甘特图 / 1 表单（PATCH `/forms/{view_id}` 设 `shared=true` 拿到 shared_url，外部用户可直接填表）
- 启动时一次性建模 + 字段类型化（含公式字段 `bitable::$table[].$field[]` 表达式 deferred creation）
- 老 base / 新 base capability detection + 自动 fallback，绝不破坏存量数据

**亮点 2：DAG 调度 + Wave 并行 + Phase 0 / Phase 1 / Phase 2 三段式**

- **Phase 0**：扫描超时「分析中」任务自动恢复（用 records/search 拿 `automatic_fields=最近更新`）
- **Phase 1**：拉「待分析」候选 → 三层降级（search+sort → search-only → list+filter）→ 依赖检查 → claim 抢占
- **Phase 2**：批量更新 / 删除 500 条/次切片 + 单片失败 fallback **严格串行 await**（避免 1254291 写冲突）

**亮点 3：观测 + 安全 + 韧性三件套**

- 结构化 JSON 日志 + ContextVar correlation_id 跨 await 边界传播
- 自动脱敏：Bearer Token / 飞书 URL token / OAuth code / userinfo @ URL / 自定义 sensitive key
- 队列 256 条上限 + 终态事件 drain-and-retry（progress_broker.py）
- 单 agent 滑动窗口熔断器（OPEN/HALF_OPEN/CLOSED）+ pipeline 级联弹性（6 上游全败仍出 CEO 报告）+ 任务取消注册表

**亮点 4：跨任务长期记忆 + 双向冲突闭环（多智能体可解释性的工程化兑现）**

- **长期记忆 wired**：CEO prompt 自动检索过往同维度任务（Jaccard 加权 title×2+dimension×0.5+background×0.3），注入 `<similar_past_analyses>` block 让 CEO 借鉴过往健康度 + 决策摘要
- **双向冲突闭环**：rule-based 检测上游 7 岗健康度硬冲突（颜色差≥2 且双方 conf≥3）→ 注入 `<conflict_alerts>` → CEO LLM 决策 → 程序化验证决策段是否 explicit 处理 → 漏报追加 thinking_process 警告
- **任务生命周期完整 CRUD**：`/seed`（dedup 防 LLM 浪费）/ `/confirm`（幂等）/ `/cancel`（主动停 in-flight）/ `/replay`（fix 后复跑，含 fresh 清缓存 checkbox）/ `/export`（Markdown 离线复盘）

**亮点 5：测试 630 passed（backend 570 + frontend 60），4 个随机种子全绿**

- Backend pytest 570 passed in 145s（含 22 轮迭代累积的回归网）
- Frontend vitest 60 passed + TypeScript tsc --noEmit clean + vite build 干净
- pytest --randomly 4 个种子（1 / 42 / 20260501 / 99999）全绿，证明无 order-dependent 状态泄漏
- 1 次真飞书 Bitable 端到端实跑：52 min / verify issues=0 / 12 表 + 24 视图 + 7 岗 DAG + CEO 综合报告 + 业务闭环
- CI gate：每次 push master 自动跑 `pytest -q + compileall`

#### 4）AI 亮点介绍

##### 高阶 AI 技巧

- **DAG 拓扑感知调度**：不是简单的"prompt chain"，而是用代码定义 7 岗依赖关系，调度器 `kahn_topological_sort` 算波次，同波次并行 `asyncio.gather`，跨波次串行
- **Prompt 模板 + 证据等级分级**：每岗输出强制带「证据来源」字段，CEO 助理基于证据等级（🧱 硬证据 / 🟡 待验证 / 软推断）决定健康度评级
- **健康度 cap 机制**：CEO 综合健康度 🟢 时紧急度 cap 在 ≤3，🟡 cap 在 ≤4，避免 LLM 输出"绿色 + 5 紧急度"的逻辑悖论（v8.6.20-r3 修复）
- **失败检测**：每岗输出过 `is_failed_result` 检查（空内容 / "FAILED:" 前缀 / 长度阈值），失败任务标记 `异常状态=已异常` 而非静默通过

##### 人和 AI 的分工

| 阶段     | AI 负责                                                    | 人负责                                   |
| -------- | ---------------------------------------------------------- | ---------------------------------------- |
| 任务录入 | 自动识别任务类型、推荐 Agent 组合                          | 写任务标题 / 上传 CSV / 调整模块         |
| 7 岗分析 | 7 个角色独立产出 + 引用证据                                | 暂无（全自动）                           |
| CEO 决策 | 综合健康度 + 紧急度 + Top3 行动项                          | **拍板**（驾驶舱回写「拍板/执行/复盘」） |
| 业务闭环 | 行动项 → 新任务 + 复核任务（按模板中心自动回填负责人/SLA） | 复核拍板 → 决定再跑 / 归档               |

##### 核心模型选型思路

- **国内大模型双备份**：默认 DeepSeek-Chat（成本最低），fallback 智谱 GLM-4 / 豆包 1.6 / 火山引擎方舟
- **不同岗位用不同 temperature**：数据分析师 / 财务顾问 temperature=0.3（要严谨），内容负责人 / SEO 顾问 temperature=0.7（要发散），CEO 助理 temperature=0.5（平衡）
- **绝对禁止 Claude/GPT**（竞赛一票否决项），代码层硬编码 base_url 校验

##### 引入 AI 后对原有工作流带来的改变

| 维度         | 传统人工               | Puff C21 AI 协同                                       |
| ------------ | ---------------------- | ------------------------------------------------------ |
| 一次复盘耗时 | 2-3 人 × 2-3 天 = ~50h | 7 岗并行 ≤1h（LLM 推理时间）                           |
| 证据可追溯   | 散落在文档 / 群聊里    | 全部沉淀到「证据链」表，硬证据 / 待验证 / 风险机会分级 |
| 决策一致性   | 主观 + 个人经验差异    | DAG 强约束 + 健康度 cap 机制                           |
| 业务闭环     | 复盘结论 ≠ 行动项落地  | CEO 行动项 → 自动写回主表 → 下一轮调度接手             |

#### 5）其他信息补充

- **代码仓库 commit 数**：本届迭代 R0 → R50 共 51 轮（每轮 audit + fix + push + 实跑验收 / 标准化提交规范）
- **测试覆盖**：backend `pytest` **570 passed in 145s** + frontend `vitest` **60 passed in 5s** = **630 tests** 全绿
- **随机序稳定性**：`pytest --randomly` 4 个种子（1 / 42 / 20260501 / 99999）全绿（v8.6.20-r48 修了 2 处隐藏的 order-dependent 缺陷）
- **Round-10 安全审计**：6 项发现（1 BLOCKER + 2 HIGH + 3 MEDIUM）已全部修复（v8.6.20-r25）；Round-11 / Round-12 自审计在 r28-r49 期间又修了 9 处真实工程缺陷
- **GitHub Pages 部署**：`.github/workflows/deploy-bitable-plugin.yml` 自动构建 + 部署，飞书插件即开即用
- **15 端点 + 完整工具链**：REST API 13 + SSE 2 + headless CLI 14 子命令 + 一键 OpenAPI 导出 + 一键验收脚本（bash / PowerShell）+ 飞书插件 UI 操作工具栏
- **不在范围内的能力**：LinkedRecord 字段写入、kanban group_field PATCH（飞书 OpenAPI v8.6.4 实证不开放，已在 docs 标注）

### 2. 小组成员各自负责部分信息

> 个人参赛跳过此节；小组参赛请每位组员补充。

---

## 三、其他信息（自由发挥区）

### 已知边界（不夸大、为后续工程化留口子）

> v8.6.20-r29 / r29 已把过去标注的 2 项硬限制（单 Base 单租户、数据源解析窄）真正修了；下表只列**当前仍存在**的 3 条边界。

| 边界                | 现状                                                            | 影响                            | 解除路径                                    |
| ------------------- | --------------------------------------------------------------- | ------------------------------- | ------------------------------------------- |
| 分布式锁多实例支持  | 单实例 in-process `asyncio.Lock` OK；多实例需挂 Redis（SET nx 已实现，缺 Redis 时降级本地锁 + WARNING） | 扩到 2+ 后端实例必须挂 Redis    | 部署文档已注明；Redis 是单一外部依赖        |
| i18n                | 表 / 字段 / Agent persona 全中文                                | 非中文场景需手翻 `schema.py`     | 抽 `i18n.json` 与 `schema.py` 解耦          |
| 飞书插件商店发布    | 已用 opdev 上传到自建空间能用；未走商店审核                      | 商店全网用户暂不可装             | 自建空间 + GitHub Pages 已可用，商店审核可选 |

**已修复（无需再标）**：
- ✅ 多 Base 隔离（v8.6.20-r29）：`_state` 单字典 → `_state_by_token` 注册表 + 8 项并发硬验收测试 + 4 种子随机序全绿
- ✅ 数据源解析覆盖（v8.6.20-r29）：CSV / TSV / 分号 / 管道 / JSON / JSONL / Markdown + `csv.Sniffer()` 自动判别 + UTF-8 BOM 剥离 + 嵌套引号 Excel 导出

### 项目工程化指标

- **代码总行数**：~35 000 行（backend Python + frontend TypeScript + 9 docs）
- **测试**：`pytest backend/tests` **570 passed in 145s** + `vitest` **60 passed in 5s** = **630 tests** 全绿；TypeScript `tsc --noEmit` 干净；4 个随机种子下 backend 仍全绿
- **CI 守门**：v8.6.20-r28 起 `.github/workflows/backend-tests.yml`，每次 push master 自动跑 `pytest -q + compileall`；前端独立 `.github/workflows/deploy-bitable-plugin.yml` 部署 GitHub Pages
- **Round 数**：从 R0 累计到 R50（51 轮 audit + fix + push + 实跑验收 / 标准化提交规范）；其中 **r28-r49 共 22 轮** 是本次复赛冲刺期增量
- **可观测性矩阵**：`/preflight`（部署体检）+ `/telemetry`（运维大盘 含熔断器 + cancellation queue）+ `/audit`（审计查询）+ `/agents`（多智能体目录）+ `/agents/{id}/profile`（单岗位画像 含 skills + active_hints + circuit_breaker）

### 飞书生态深度集成清单

| 能力                                 | 实现                                                                               | 状态                                  |
| ------------------------------------ | ---------------------------------------------------------------------------------- | ------------------------------------- |
| Bitable OpenAPI 真实调用             | `feishu/bitable.py` + `bitable_workflow/bitable_ops.py`                            | ✅ 无 Mock                            |
| 多维表格插件（base-extension）       | `frontend/bitable.html` + `BitableAgentLauncher.tsx` + `BitableWorkflowPlugin.tsx` | ✅ 已部署 GitHub Pages + opdev upload |
| 飞书 Tasks（CEO 行动项同步）         | `feishu/tasks.py::create_task`                                                     | ✅                                    |
| 飞书 IM 富文本卡片（健康度颜色映射） | `feishu/im.py::send_card_message`                                                  | ✅                                    |
| 飞书 OAuth 用户态视图配置            | `feishu/user_token_view_setup.py`                                                  | ✅                                    |
| 表单分享链接（外部填报）             | `_share_form_view` PATCH `shared=true`                                             | ✅                                    |
| 仪表盘 list（Dashboard API）         | `feishu/dashboard_picker.py`                                                       | ✅（仅可读）                          |

### 提交前 Checklist

- [ ] 文档「互联网获取链接可阅读权限」已开启 ⏳ 提交时
- [x] 个人信息表格已填写完整 ✅ 已填
- [ ] Demo 录屏链接已上传（建议路径见 §1.1，3-5 min）⏳ 待录
- [x] Bitable Demo URL 仍可访问 ✅ https://feishu.cn/base/GXkTbYLn9a3WRbswJ99crIcMnvh
- [x] 代码仓库链接公开可访问 ✅ https://github.com/shuaigexly/-multiagent
- [x] OpenAPI spec 已生成可分享 ✅ docs/openapi.json（55 paths / 58 ops）
- [x] 一键验收脚本可用 ✅ `bash scripts/verify.sh` / `powershell scripts\verify.ps1`

### r28-r49 完整迭代清单（提交时可作为「亮点压缩展示」）

> 22 轮迭代 / 630 tests / 15 REST endpoints + 2 SSE / 4 种子随机序全绿

#### 5 大创新主线

| 主线                | 涉及 Round            | 价值定位                                                                                                                                                              |
| ------------------- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. 双向冲突闭环** | r33 + r36             | 程序化检测 → `<conflict_alerts>` 注入 CEO prompt → CEO LLM 决策 → 程序化验证决策段是否处理 → 漏报追加警告。AI 工程化深度的核心展示。                                  |
| **B. 长期记忆**     | r40 + r42             | Jaccard 加权检索过往同维度任务 → 注入 `<similar_past_analyses>` block → CEO 借鉴过往健康度评级 + 决策摘要。让多智能体系统拥有「我以前分析过类似问题」的记忆。         |
| **C. 韧性三件套**   | r32 + r41 + r43 + r44 | 6 上游 LLM 全败仍出 CEO 报告 / 单 agent 滑动窗口熔断器 / 任务取消注册表 / fix 后复跑。生产级容错 + 主动控制。                                                         |
| **D. 任务生命周期** | r38 + r43 + r44 + r34 | seed 自动 dedup（防 LLM 浪费）/ cancel 主动停 in-flight / replay 修复后复跑 / export 导出 Markdown。完整 CRUD 语义。                                                  |
| **E. 数据基础**     | r29                   | \_state 单字典 → per-app_token 注册表（多租户隔离 + 8 项并发硬验收）；data_parser 从 2 格式扩到 7 种（CSV/TSV/分号/管道/JSON/JSONL/Markdown + Sniffer + UTF-8 BOM）。 |

#### 15 端点 surface

| 类别          | 端点                                                                    |
| ------------- | ----------------------------------------------------------------------- |
| 部署          | `/preflight`                                                            |
| 调度          | `/setup` `/start` `/stop` `/status`                                     |
| 任务生命周期  | `/seed`（dedup） `/confirm`（幂等） `/cancel/{rid}` `/replay/{rid}`     |
| 数据查询      | `/records` `/native-assets` `/native-manifest` `/native-manifest/apply` |
| 流式          | `/stream-token/{rid}` `/stream/{rid}`                                   |
| 沉淀 / 可观测 | `/export/{rid}`（Markdown）`/telemetry` `/audit` `/similar`（长期记忆） |
| Agent 元数据  | `/agents` `/agents/{id}/profile`                                        |

#### 工程工具链

- **OpenAPI 3.x spec**：`docs/openapi.json`（55 paths / 58 ops），可直接导入 Swagger UI / Postman 自助探查
- **Headless CLI**：`python -m app.cli <14 个子命令>`，环境变量 `PUFF_C21_API_BASE` / `PUFF_C21_API_KEY` 配后端
- **飞书插件 UI 工具栏**：`TaskActionsToolbar` 三按钮（下载 Markdown / 取消任务 / 复跑任务）直接嵌入 Bitable 插件运行视图
- **一键验收脚本**：`bash scripts/verify.sh --with-randomly --with-frontend`（POSIX）/ `powershell scripts/verify.ps1 -WithRandomly -WithFrontend`（Windows）

#### 测试矩阵

| 项                                      | 数据                                                           |
| --------------------------------------- | -------------------------------------------------------------- |
| Backend pytest                          | **570 passed** in 145s                                         |
| Frontend vitest                         | **60 passed** in 5s                                            |
| TypeScript tsc --noEmit                 | clean                                                          |
| 随机序稳定（4 seeds）                   | 全绿（seed 1 / 42 / 20260501 / 99999）                         |
| CI gate                                 | `.github/workflows/backend-tests.yml` 每次 push 触发           |
| 端到端实跑（v8.6.20-r51 / 2026-05-01） | Bitable `T2QibqZe5aZa6mseY1UcF5A0n1f`，verify issues=0，50 min（最新 / 含 r28-r49 全量特性）|
| 端到端实跑（v8.6.20-r25 / 2026-04-30） | Bitable `GXkTbYLn9a3WRbswJ99crIcMnvh`，verify issues=0，52 min（基线对比）|
