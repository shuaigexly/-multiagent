# 自评：项目对照三维评分标准的诚实差距

> 本文是基于 v8.6.20-r28 当前代码状态做的内部自评，目的不是宣传，而是把
> 我们自己已经看到的差距公开摆出来，配套修复路径与缓解措施。
> 内容来自 Round-11 完整审计 + 全量 pytest 417 passed + 真飞书 Bitable 实跑。

---

## 维度 1 · 完整性与价值（50%）

### ✅ 已落地

| 检查点 | 实证 |
|---|---|
| 痛点定义清楚 | 复杂经营 / 立项 / 风险 / 内容协作任务，单 Agent + 单工具不够；7 岗 DAG 一站式协同 |
| AI 起到关键作用 | 7 岗每岗独立 LLM 调用 + 证据等级标注 + 健康度 cap 机制；CEO 助理基于上游汇总而非裸调 LLM |
| 流程闭环 | 真实 Bitable 实跑确认 — CEO 行动项 → 写回主表「待分析」→ 调度循环下一轮接手；`scheduler.py::_create_followup_tasks` 限定前 3 条 + `[跟进]` 前缀防无限循环 |
| Demo 稳定性 | v8.6.20-r25 在 `GXkTbYLn9a3WRbswJ99crIcMnvh` 跑通 52 min 端到端，verify_bitable issues=0 |
| 实际价值 | 7 岗并行 ≤1 h vs 传统 50 h 人工复盘；证据全沉淀「证据链」表硬证据 / 待验证 / 风险机会分级 |

### ⚠️ 已知差距

| 差距 | 严重度 | 现状 | 缓解 / 修复 |
|---|---|---|---|
| ~~单 Base 单租户~~ | ~~HIGH~~ | **v8.6.20-r29 已修**：`_state` 改为 `_state_by_token` 注册表，每 `app_token` 独享 bucket；GET 端点支持 `?app_token=` 显式指定；旧前端 0 改动兼容；新增 8 项隔离回归测试 | ✅ Done |
| Demo 视频未录 | MEDIUM | docs 内有完整文字脚本与已跑数据 | 5 月 7 日提交前补录 3-5 min 屏录上传 GitHub Releases |
| ~~数据源解析窄~~ | ~~MEDIUM~~ | **v8.6.20-r29 已扩展**：用 `csv.Sniffer` 自动判别 delimiter，新增 TSV / 分号 / 管道 + JSON 数组 / JSONL（NDJSON）+ UTF-8 BOM 剥离；RFC 4180 含嵌套引号 Excel 导出走 csv 模块；14 项格式回归测试 | ✅ Done |

---

## 维度 2 · 创新性（25%）

### ✅ 差异化点

1. **不是 prompt chain 而是 DAG 调度** — `registry.py::AGENT_DEPENDENCIES` 用代码定义 7 岗依赖图，调度器拓扑排序自动分波次并行，跨波次串行；同波次 `asyncio.gather` 并发
2. **健康度 cap 机制** — CEO 综合健康度 🟢 时紧急度 cap ≤3，🟡 cap ≤4，避免 LLM 输出"绿色 + 5 紧急度"逻辑悖论（v8.6.20-r3 修复）
3. **证据等级分级** — 每岗输出强制「证据来源 + 引用」，硬证据 / 待验证 / 软推断三级，CEO 据此决定健康度评级
4. **业务闭环 = 自动写回新任务** — vs 飞书原生 Agent 输出文本一次性结束；我们 CEO 行动项 → 新「待分析」记录 → 下一轮调度接手 → 形成持续业务流
5. **失败任务标记非静默通过** — `is_failed_result` 检查每岗输出（空 / "FAILED:" / 长度阈值），失败标记 `异常状态=已异常` 而非伪装成功

### ✅ 可复用 / 可推广

- **Agent Registry 插件化** — 加新岗只需在 `registry.py` 注册 + 写 `agents/<role>.py` prompt 模板，DAG 自动接入
- **模板配置中心表** — Bitable 里有真实「模板配置中心」表存模板，可在线改 prompt / SLA / 责任人，无需改代码
- **多模型可换** — 默认 deepseek-chat，env 切智谱 GLM / 火山方舟 / 通义 / 豆包 / MiniMax
- **Bitable Plugin** — 已部署 GitHub Pages，飞书侧 OAuth 后即开即用，可被任何 Base 加载

---

## 维度 3 · 技术实现性（25%）

### ✅ AI 技术深度

- 7 个独立 LLM 调用 + 角色化温度（数据 / 财务 0.3 严谨；内容 / SEO 0.7 发散；CEO 0.5 平衡）
- DAG 拓扑排序 + 同波次并行 + 跨波次串行
- 真飞书 OpenAPI（无 Mock）— Bitable / Tasks / IM / OAuth / 表单分享 / Dashboard list
- 证据 + 失败 + 健康度 cap 三层决策约束

### ✅ 架构合理性

- **观测**：`observability.py` ContextVar 4 字段（correlation_id / task_id / agent_id / tenant_id）跨 await 边界传播 + 结构化 JSON 日志 + 自动脱敏（Bearer / 飞书 URL token / OAuth code / userinfo @ URL）
- **韧性**：`feishu/retry.py` 指数退避 + 401 自动 refresh token + 4xx 配置错误快速失败；`bitable_ops.py` records/search 自动剥离 `automatic_fields` 重试；500 条/次切片 + 单片失败 fallback 严格串行（避免 1254291 写冲突）
- **降级**：`agents/fallback.py` LLM 失败时启用规则化 persona-aware 骨架输出，pipeline 不崩
- **流式**：SSE token 短时签发 + audience 绑定；`progress_broker.py` 队列 256 条上限 + 终态事件 drain-and-retry

### ✅ 工程规范

- **测试 417 passed** in 142 s（含 v8.6.19/20 多轮 audit 回归 + 输入边界 + 视图表面 + LLM planner audit）
- **CI 守门**：v8.6.20-r28 起 `.github/workflows/backend-tests.yml` 每次 push 跑 `pytest -q` + `python -m compileall`
- **Round-10 安全审计**：6 项发现已全部修复（1 BLOCKER + 2 HIGH + 3 MEDIUM）— `_JsonFormatter %f` Win 兼容、`_KEY_VALUE_RE` 双重 `[REDACTED]]` 截断、`_ContextFilter` 不覆盖 caller extra、`_CLI_ENV_ALLOWLIST` 加 Windows 必备 env、`redact_sensitive_text` 区分 None/0/False、`redact_sensitive_data` 覆盖 bytes/Exception/对象
- **Round-11 doc / test drift 修复**（v8.6.20-r26）：blueprint §7 视图清单对齐 curated plan；test_bitable_surface noisy_views 加 9 项历史切片
- **代码风格**：v8.6.20-r27 把 `workflow_records` inline trim 收编进 `_normalize_optional_query_string` helper，与同模块 `_normalize_path_id` 模式对齐

### ⚠️ 工程差距

| 差距 | 严重度 | 缓解 |
|---|---|---|
| ~~`_state` 全局字典~~ | ~~HIGH~~ | **v8.6.20-r29 已修** — 注册表 + 8 项隔离测试 |
| ~~数据源解析窄~~ | ~~MEDIUM~~ | **v8.6.20-r29 已修** — Sniffer + 7 种格式 + 14 项测试 |
| Demo 视频未录 | MEDIUM | 提交前补录 |
| i18n 全中文 | LOW | 评审场景中文，竞赛不阻塞 |

---

## 综合判断

| 维度 | 自评 | 主因 |
|---|---|---|
| 完整性与价值（50%） | 9.5 / 10 | 闭环真实跑通 + verify=0；多 Base 隔离 + 7 数据格式 + 任务生命周期端点（seed dedup / cancel / replay）+ 长期记忆 wired into CEO；剩余仅 Demo 视频 |
| 创新性（25%） | 9.5 / 10 | DAG + 健康度 cap + 证据等级 + 双向冲突闭环（r33+r36）+ 跨任务 Jaccard 长期记忆（r40+r42）+ 单 agent 熔断器（r41）+ 任务生命周期管理（r38+r43+r44）|
| 技术实现性（25%） | 9.7 / 10 | 测试 630（backend 570 + frontend 60）+ CI gate + 多租户 + 韧性 + 体检 + 幂等 + 熔断 + 审计 + 取消 + Markdown 导出 + 遥测大盘 + 多 agent 可观测性 + OpenAPI spec + headless CLI + 飞书插件 UI 工具栏 + 4 种子随机序稳定性 |

**加权 ≈ 9.6 / 10。** r28-r49 共 22 轮迭代，417 → 630 tests，6 端点 → 15 端点，新增 5 大创新主线。

### r28-r49 完整里程碑

| Round | 主题 | 测试增量 |
|---|---|---|
| r28 | CI pytest gate + 提交稿 + 三维自评 + 边界文档 | - |
| r29 | multi-tenant `_state` 注册表 + 7 数据格式 + Sniffer | +22 |
| r30 | `/confirm` 幂等 + datetime warning 清零 | +3 |
| r31 | multi-tenant 并发硬验收 | +2 |
| r32 | pipeline 级联弹性（6 上游全败仍出 CEO 报告）| +3 |
| r33 | 跨 agent 健康度冲突检测器 | +12 |
| r34 | `/export/{record_id}` Markdown 导出 | +5 |
| r35 | `/telemetry` + reasoning_tokens | +5 |
| r36 | 冲突检测器闭环 post-LLM 验证 | +7 |
| r37 | `/preflight` 4-check 部署体检 | +6 |
| r38 | `/seed` dedup guard | +6 |
| r39 | `/audit` 审计日志查询 | +5 |
| r40 | 跨任务相似度检索（Jaccard 加权）| +17 |
| r41 | 单 agent 熔断器 + telemetry 曝光 | +10 |
| r42 | 长期记忆 wired into CEO prompt | +5 |
| r43 | 任务取消注册表 + `/cancel/{record_id}` | +11 |
| r44 | `/replay/{record_id}` 闭合 cancel→fix→replay | +8 |
| r45 | `/agents` catalog + `/agents/{id}/profile` | +8 |
| r46 | 自审计修复（cancellation LRU + ## /### 标题 + telemetry queue size）| +6 |
| r47 | OpenAPI spec 一键导出 + headless CLI（14 子命令）| +12 |
| r48 | pytest --randomly 修 2 处 order-dependent 缺陷（4 种子稳定）| 0 |
| r49 | 飞书插件 UI 任务操作工具栏（下载 / 取消 / 复跑）| +8 |

### 提交前 checklist

1. ✅ CI pytest gate（r28）
2. ✅ 多 Base 隔离 + 数据源 7 格式（r29）
3. ✅ 全链路韧性（r30 / r32 / r41 / r43 / r44）
4. ✅ 双向冲突闭环（r33 + r36）
5. ✅ 长期记忆 + retrieval（r40 + r42）
6. ✅ 任务生命周期端点（r38 / r43 / r44）
7. ✅ 多智能体可观测性（r35 / r39 / r45）
8. ✅ 工程工具链（r47 OpenAPI + CLI）
9. ✅ 随机序测试稳定性（r48 4 种子全绿）
10. ✅ 飞书插件 UI 串联（r49）
11. ⏳ 录 Demo 视频（人工，5 月 7 日前）
12. ⏳ 个人信息表格填写（人工，提交时）
