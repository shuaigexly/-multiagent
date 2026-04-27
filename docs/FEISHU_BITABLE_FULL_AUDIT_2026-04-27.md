# 飞书多维表格闭环系统全量审计

> 审计时间：2026-04-27 21:46:54 CST  
> 范围：文档契约、后端 API、调度器、原生安装器、前端工作台、自动化日志、测试与构建  
> 基准：以仓库现状与飞书多维表格原生化目标为准，不以局部修复通过为止

---

## 1. 审计方法

本轮不再按单点 bug 逐个找，而是按 5 层契约做整链路检查：

1. 文档层
   - README、原生安装包、蓝图、验收边界之间是否描述一致
2. 接口层
   - 前端请求参数、后端请求校验、installer 内部 surface 集合是否一致
3. 状态机层
   - 工作流路由、驾驶舱确认动作、原生责任状态是否允许非法跳转
4. 执行层
   - follow-up / recheck / native apply 是否会重复创建、越级执行或错分支
5. 验证层
   - `pytest -q`
   - `npm run build`
   - `npm run lint`

---

## 2. 本轮确认修复的问题

### F1. follow-up 任务会重复创建

- 位置：`backend/app/bitable_workflow/scheduler.py`
- 问题：复核任务有去重，`[跟进]` 任务没有对未关闭同名记录做去重
- 风险：同一 CEO 行动项在多轮调度中膨胀成重复任务
- 结果：已修复，并补回归测试

### F2. `等待拍板` 路由会提前创建执行任务

- 位置：`backend/app/bitable_workflow/scheduler.py`
- 问题：只要存在 `execute_now/delegated` 项，系统就会置 `待创建执行任务=True` 并尝试创建飞书任务
- 风险：还没拍板就提前执行，破坏多维表格原生工作流分支语义
- 结果：已改为只有 `直接执行` 路由才允许创建执行任务

### F3. 驾驶舱确认接口允许非法状态跳转

- 位置：`backend/app/api/workflow.py`
- 问题：`workflow_confirm` 未校验当前路由与动作是否匹配
- 风险：`等待拍板` 任务可被直接标记为“执行落地”
- 结果：已增加 409 阻断与回归测试

### F4. `advperm` surface 文档存在、API 不接受

- 位置：
  - `backend/app/api/workflow.py`
  - `frontend/src/services/workflow.ts`
  - `frontend/src/pages/BitableWorkflow.tsx`
- 问题：文档、manifest、installer 都支持 `advperm`，但请求校验和前端 surface 类型缺失
- 风险：高级权限无法被单独原生化，角色前置能力名义上存在、实际上不可调用
- 结果：已补齐 API / 前端类型 / 选择器 / 默认值

### F5. `advperm only` 会误触发全量 native apply

- 位置：`backend/app/bitable_workflow/native_installer.py`
- 问题：installer 内部 `_ALL_SURFACES` 未包含 `advperm`，导致 `surfaces=["advperm"]` 过滤后变空，再退回全量 surface
- 风险：用户只想开高级权限，实际却跑了 form / workflow / dashboard / role
- 结果：已修复为真正的一等 surface，并补了只跑 `+advperm-enable` 的回归测试

### F6. 前端页面仍保留默认模板 metadata

- 位置：`frontend/index.html`
- 问题：仍是 `Lovable App`、`Lovable Generated Project` 与 TODO 注释
- 风险：产品标题、SEO、分享卡片全部错误，不符合交付态
- 结果：已改为项目真实标题与描述

### F7. `BitableWorkflow` 原生资产统计依赖不稳定

- 位置：`frontend/src/pages/BitableWorkflow.tsx`
- 问题：`nativeAssetCounts = ... || {}` 每次 render 都生成新对象，触发 `useMemo` 依赖警告
- 风险：统计面板重复计算，lint 持续报警
- 结果：已修复依赖稳定性

### F8. `Index` 页面存在无效动态导入

- 位置：`frontend/src/pages/Index.tsx`
- 问题：`config.ts` 被动态导入，但同一模块又在其他页面静态导入
- 风险：不会产生真实分包，只会留下构建告警并增加依赖图复杂度
- 结果：已改为静态导入

### F9. 页面路由未做懒加载，前端主包偏大

- 位置：`frontend/src/App.tsx`
- 问题：首页、结果页、工作流页、设置页等全部静态进入主路由树
- 风险：初始加载负担过重，构建产物过大
- 结果：已改为 `React.lazy + Suspense` 路由懒加载

### F10. `ResultView` 图表库耦合导致单 chunk 过大

- 位置：
  - `frontend/src/pages/ResultView.tsx`
  - `frontend/src/components/ResultCharts.tsx`
- 问题：`recharts` 直接跟随结果页打进同一个 chunk，结果页单包一度超过 500k
- 风险：构建告警持续存在，结果页首次加载成本过高
- 结果：已把图表渲染拆成独立懒加载组件，500k chunk 告警消失

### F11. lint 剩余 warning 来自组件导出组织

- 位置：
  - `frontend/src/components/ModuleCard.tsx`
  - `frontend/src/components/agentPersonas.ts`
  - `frontend/src/components/ui/*`
- 问题：persona 常量与 shadcn/ui 样式工厂导出触发 `react-refresh/only-export-components`
- 风险：静态检查长期噪音，真正 warning 容易被淹没
- 结果：
  - `AGENT_PERSONAS` 已拆到独立文件
  - `src/components/ui/**/*` 加了定向 ESLint 例外
  - `npm run lint` 已清零

---

## 3. 全量验证结果

### 后端

```bash
pytest -q
```

结果：

- `273 passed, 3 skipped`

### 前端构建

```bash
npm run build
```

结果：

- 构建通过
- 500k chunk 告警已消失
- 仍有 `vite:react-swc` 的 `esbuild` deprecation warning，属于工具链升级项，不是业务代码错误

### 前端静态检查

```bash
npm run lint
```

结果：

- 无 error
- 无 warning

---

## 4. 当前系统结论

截至本轮，系统已经从“局部功能可用”提升到“关键契约已闭环”：

- 原生化 surface 契约已贯通：前端 -> API -> installer
- 工作流状态机不再允许明显越级动作
- `等待拍板` / `直接执行` / `补数复核` 分支语义更接近文档定义
- 跟进任务与复核任务都具备未关闭记录去重
- 前端展示层不再携带模板脚手架默认文案

---

## 5. 剩余非阻断项

这些不是本轮已确认的线上 bug，但仍建议后续继续治理：

1. `vite:react-swc` 仍提示 `esbuild` deprecation
   - 属于工具链升级项，可后续评估迁移到推荐的 `oxc` 配置
2. 真实飞书租户写入权限仍受外部环境限制
   - 当前仓库只能证明代码链路和 mock/测试链路正确
   - 不能在没有真实租户权限的情况下声称“线上飞书原生写入全部实测通过”

---

## 6. 建议的后续审计方式

后续不要再按“某个文件看起来可疑”零散修。建议固定为：

1. 先更新文档契约
2. 再核对前后端请求结构
3. 再核对 scheduler / workflow_confirm / native_installer 的状态机
4. 最后统一跑：
   - `pytest -q`
   - `npm run build`
   - `npm run lint`

只有这样，才能避免“局部修好了，系统契约却又断了一处”。
