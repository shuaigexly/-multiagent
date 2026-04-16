# 飞书 AI 工作台 — 完整验收测试手册

> 面向：QA、交接接收方、产品验收  
> 覆盖：所有功能模块的端到端验收用例  
> 前提：已按 HANDOVER.md 完成本地或生产环境部署

---

## 环境准备

```bash
# 1. 启动后端
cd backend
cp .env.example .env   # 填写 LLM_API_KEY
uvicorn app.main:app --reload --port 8000

# 2. 启动前端
cd frontend
echo "VITE_API_URL=http://localhost:8000" > .env
npm run dev
# 访问 http://localhost:5173

# 3. 验证服务健康
curl http://localhost:8000/health
# 预期：{"status":"ok","service":"feishu-ai-workbench"}
```

---

## 模块一：任务提交与规划

### TC-01 提交任务，LLM 自动规划模块

**前提**：LLM 已配置可用

**步骤**：
1. 打开工作台首页
2. 在输入框输入："分析我们上季度的销售数据，找出增长点和风险"
3. 点击「提交」

**预期**：
- 页面跳转到任务规划页
- 显示任务类型（如"数据分析报告"）
- 至少推荐 `data_analyst` 模块，并包含 `ceo_assistant`
- 各模块卡片展示正确的 avatar、名称、职位描述

---

### TC-02 调整模块组合后确认

**步骤**：
1. 在规划页取消勾选 `finance_advisor`
2. 手动勾选 `seo_advisor`
3. 点击「开始分析」

**预期**：
- 确认后任务进入执行状态
- 执行时间线展示已选模块（不含未选模块）

---

### TC-03 取消正在执行的任务

**步骤**：
1. 提交任务并确认
2. 在执行过程中点击「取消」

**预期**：
- 任务状态变为 `cancelled`
- 页面提示取消成功
- 后端日志无报错

---

## 模块二：多 Agent 执行与 SSE 流

### TC-04 Agent 波次执行顺序验证

**步骤**：
1. 选择全部 7 个模块后提交
2. 观察执行时间线

**预期**：
- `data_analyst` 先于 `finance_advisor` 完成（有依赖关系）
- `ceo_assistant` 最后完成
- 其余无依赖模块并行出现在同一波次

---

### TC-05 SSE 实时推送

**步骤**：
1. 提交任务执行
2. 打开浏览器开发者工具 → Network → 筛选 `stream`

**预期**：
- 能看到 SSE 长连接建立
- 每个 Agent 开始/完成时分别有 `module.started` / `module.completed` 事件推送
- 所有模块完成后收到 `stream.end` 事件

---

### TC-06 单个 Agent 失败不影响整体

**步骤**（需模拟 LLM 超时，可临时设置无效 model）：
1. 临时修改某一 Agent 的 SYSTEM_PROMPT 触发极短输出
2. 观察执行是否继续

**预期**：
- 失败 Agent 显示 FAIL 状态
- 其他 Agent 继续正常完成
- 最终任务状态为 `done`（部分结果）

---

## 模块三：分析结果查看

### TC-07 结果页完整展示

**步骤**：
1. 等待任务完成
2. 进入结果页

**预期**：
- 每个参与的 Agent 都有对应的结果卡片
- 各卡片展示对应的分析章节（标题 + 内容）
- 行动建议列表非空

---

### TC-08 结果数据持久化

**步骤**：
1. 完成一次任务
2. 刷新页面
3. 从任务列表重新进入该任务的结果页

**预期**：
- 结果完整保留，无数据丢失
- 任务状态保持 `done`

---

## 模块四：飞书发布 — 文档 / 多维表格 / 演示文稿

> 前提：已配置 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`，飞书应用已上线

### TC-09 发布飞书文档

**步骤**：
1. 在结果页选择「飞书文档」
2. 点击「发布」

**预期**：
- 页面展示文档链接
- 点击链接能在飞书中打开文档
- 文档包含各 Agent 的分析章节（Heading / 段落块）

---

### TC-10 发布多维表格

**步骤**：
1. 选择「多维表格」
2. 点击「发布」

**预期**：
- 返回多维表格链接
- 表格包含「分析结果」和「行动项」两个 sheet
- 各 Agent 的行动项作为独立行存在

---

### TC-11 发布演示文稿

**步骤**：
1. 选择「演示文稿」
2. 点击「发布」

**预期**：
- 返回演示文稿链接（或降级为文档链接）
- 内容按分析章节组织

---

## 模块五：飞书发布 — 群消息 / 互动卡片（有 chat_id）

> 前提：已知目标群的 chat_id，机器人已被加入该群

### TC-12 发群消息（有 chat_id）

**步骤**：
1. 在结果页发布配置填写 `chat_id`
2. 选择「群消息」
3. 点击「发布」

**预期**：
- 目标飞书群收到摘要消息（包含任务类型 + 模块数量）
- 返回 `message_id`

---

### TC-13 发互动卡片（有 chat_id）

**步骤**：
1. 填写 `chat_id`，选择「互动卡片」
2. 点击「发布」

**预期**：
- 目标飞书群收到蓝色标题卡片
- 卡片展示各 Agent 分析摘要（≤3 章节）和行动建议（≤5 条）

---

## 模块六：DM 兜底（无 chat_id 时私信发送）

> 前提：已完成飞书 OAuth 授权（见 TC-19）

### TC-14 群消息 DM 兜底

**步骤**：
1. 不填写 chat_id
2. 选择「群消息」
3. 观察发布按钮和提示文案

**预期**：
- 发布按钮**不**被禁用（已授权时）
- 按钮下方出现提示："未填写群 ID，将通过私信发给已授权飞书用户"
- 点击「发布」后，飞书授权用户的私信中收到摘要消息

---

### TC-15 互动卡片 DM 兜底

**步骤**：
1. 不填写 chat_id
2. 选择「互动卡片」
3. 点击「发布」

**预期**：
- 飞书授权用户的私信中收到互动卡片
- 返回的 URL 可正常打开（URL 来自响应体的 chat_id，非输入 open_id）

---

### TC-16 未授权时无 chat_id 的拦截

**步骤**：
1. 确保未完成 OAuth 授权（或清除 token）
2. 不填 chat_id，选择「群消息」

**预期**：
- 发布按钮**被禁用**
- 无 DM 兜底提示文字
- 提交时返回 400 错误，提示友好文案（非 500）

---

## 模块七：飞书 Bot 事件订阅（@机器人触发分析）

> 前提：飞书应用已在开放平台配置事件订阅，回调地址 `{后端URL}/api/v1/feishu/bot/event`，已订阅 `im.message.receive_v1`

### TC-17 URL Challenge 验证

**步骤**（在飞书开放平台保存回调地址时自动触发，也可手动模拟）：
```bash
curl -X POST http://localhost:8000/api/v1/feishu/bot/event \
  -H "Content-Type: application/json" \
  -d '{"type":"url_verification","challenge":"abc123xyz"}'
```

**预期**：
- 响应：`{"challenge":"abc123xyz"}`
- HTTP 200，3 秒内返回

---

### TC-18 群聊 @机器人 触发分析

**步骤**：
1. 在已订阅的飞书群中，@ 机器人并发送："分析我们团队本月的工作进展"
2. 等待机器人回复

**预期**：
- 机器人在原消息线程内回复："正在分析，请稍候..."（3 秒内）
- 后台异步执行多 Agent 分析
- 分析完成后在同一线程内回复：分析摘要 + 完整报告链接（`{FRONTEND_BASE_URL}/results/{task_id}`）

---

### TC-19 Bot 幂等去重

**步骤**（模拟飞书重试）：
```bash
# 发送相同 event_id 两次
curl -X POST http://localhost:8000/api/v1/feishu/bot/event \
  -H "Content-Type: application/json" \
  -d '{"header":{"event_id":"test-dup-001","event_type":"im.message.receive_v1"},"event":{"sender":{"sender_type":"user"},"message":{"message_type":"text","chat_type":"p2p","content":"{\"text\":\"测试\"}"}}}'

# 再发一次相同 event_id
curl -X POST http://localhost:8000/api/v1/feishu/bot/event \
  -H "Content-Type: application/json" \
  -d '{"header":{"event_id":"test-dup-001","event_type":"im.message.receive_v1"},"event":{"sender":{"sender_type":"user"},"message":{"message_type":"text","chat_type":"p2p","content":"{\"text\":\"测试\"}"}}}'
```

**预期**：
- 两次都返回 200
- 数据库中 `feishu_bot_events` 只有一条 `event_id=test-dup-001` 的记录
- 后端日志第二次出现 "Bot event 重复，已忽略"

---

### TC-20 Bot 自回环防护

**步骤**：模拟机器人自身发送的事件（sender_type 为 bot）

```bash
curl -X POST http://localhost:8000/api/v1/feishu/bot/event \
  -H "Content-Type: application/json" \
  -d '{"header":{"event_id":"test-bot-self","event_type":"im.message.receive_v1"},"event":{"sender":{"sender_type":"bot"},"message":{"message_type":"text","chat_type":"group_chat","content":"{\"text\":\"我自己发的\"}"}}}'
```

**预期**：
- 返回 200 `{"ok": true}`
- `feishu_bot_events` 中无新记录
- 不触发任何分析任务

---

## 模块八：飞书 OAuth 授权

### TC-21 完整 OAuth 授权流程

**步骤**：
1. 进入「设置」页面
2. 点击「授权飞书任务」
3. 在弹出的飞书授权页面同意授权
4. 授权完成后回到工作台

**预期**：
- 设置页显示"授权状态：已授权"
- `/api/v1/feishu/oauth/status` 返回 `{"authorized": true}`
- 飞书任务 API 可正常使用（任务模块创建的任务归属当前用户）

---

### TC-22 服务重启后 Token 恢复

**步骤**：
1. 完成 OAuth 授权
2. 重启后端服务
3. 检查授权状态

**预期**：
- `GET /api/v1/feishu/oauth/status` 仍返回已授权
- 后端启动日志出现"已从数据库恢复飞书用户 OAuth token"

---

## 模块九：设置页配置管理

### TC-23 LLM 配置保存与生效

**步骤**：
1. 进入「设置」→「LLM 配置」
2. 填写 API Key、Base URL、Model
3. 点击「保存」
4. 重启服务后验证配置保留

**预期**：
- 保存成功提示
- 重启后配置从 DB 恢复，无需重新填写

---

### TC-24 飞书 Bot 配置

**步骤**：
1. 进入「设置」→「飞书配置」→「Bot 事件订阅」
2. 填写 Verification Token
3. 查看展示的回调地址

**预期**：
- 回调地址显示为 `{VITE_API_URL}/api/v1/feishu/bot/event`（后端地址，非 `localhost:5173`）
- 保存 Token 后，`/api/v1/config` 中 `feishu_bot_verification_token` 有值

---

### TC-25 健康检查 API

```bash
curl http://localhost:8000/health
```

**预期**：
```json
{"status": "ok", "service": "feishu-ai-workbench"}
```

---

## 模块十：异常与边界场景

### TC-26 上传文件作为分析数据源

**步骤**：
1. 上传一个 CSV 文件（含表头和数据行）
2. 提交分析任务

**预期**：
- 任务规划页提示"已检测到上传文件"
- Agent 分析结果中引用了文件数据（列名/预览内容）

---

### TC-27 无文件无飞书上下文时的降级

**步骤**：
1. 不上传文件，不配置飞书
2. 输入任务："帮我写一份产品需求文档模板"
3. 提交执行

**预期**：
- 任务正常执行，LLM 基于任务描述本身生成结果
- 无报错，结果质量正常

---

### TC-28 并发任务超限

**步骤**：
1. 设置 `MAX_CONCURRENT_TASKS=1`
2. 同时提交两个任务并确认执行

**预期**：
- 第二个任务返回 429 或友好的排队提示
- 不影响第一个任务正常完成

---

### TC-29 服务重启后遗留任务恢复

**步骤**：
1. 提交任务并确认（使其进入 running 状态）
2. 强制重启后端服务
3. 查询该任务状态

**预期**：
- 该任务状态变为 `failed`
- 错误信息为"service restarted, task interrupted"
- 不影响新任务提交

---

## 快速冒烟测试（5 分钟最小验证集）

适用于部署后快速确认核心链路是否可用：

| # | 测试 | 通过标准 |
|---|------|---------|
| S1 | `curl /health` | 返回 `{"status":"ok"}` |
| S2 | 提交任务 → 等待完成 | 至少 1 个 Agent 返回结果，任务状态 `done` |
| S3 | 进入结果页 | 有分析内容展示，无页面报错 |
| S4 | POST `/feishu/bot/event` challenge | 返回 `{"challenge":"..."}` |
| S5 | 设置页保存 LLM 配置 | 保存成功，刷新后配置保留 |

---

## 验收结论记录

| 模块 | 验收人 | 通过/不通过 | 备注 |
|------|--------|------------|------|
| 任务提交与规划 | | | |
| 多 Agent 执行与 SSE | | | |
| 分析结果查看 | | | |
| 飞书文档/多维表格/演示文稿 | | | |
| 群消息/互动卡片（有 chat_id） | | | |
| DM 兜底（无 chat_id） | | | |
| Bot 事件订阅（@触发） | | | |
| 飞书 OAuth 授权 | | | |
| 设置页配置管理 | | | |
| 异常与边界场景 | | | |
