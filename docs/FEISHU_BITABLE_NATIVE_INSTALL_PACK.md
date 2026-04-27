# 飞书多维表格原生安装包说明

本文档解释仓库里的 `native_manifest` / `native_installer` 在做什么，以及它们如何把“多 Agent 产出”继续推进成“飞书多维表格原生交付闭环”。

---

## 1. 为什么还需要安装包

当前仓库已经完成了三层能力：

1. 多 Agent 分析结果已经被沉淀到主表字段契约里。
2. setup 会真实创建 Base、本体 12 张表、业务视图、表单视图、模板中心。
3. 前端驾驶舱已经改成优先消费主表原生字段，而不是自己推断状态机。

但这还不等于“已经原生化完成”。

真正决定飞书内交付体验的，仍然是这些云侧原生对象：

- 自动化
- 工作流
- 仪表盘
- 高级权限 / 角色工作面

所以仓库必须继续输出“可执行安装包”和“可直接 apply 的 scaffold”，而不是只留一堆说明文。

---

## 2. `native_manifest` 现在提供什么

`GET /api/v1/workflow/native-manifest` 当前返回的是 **v2 manifest**，里面不只是骨架说明，而是更接近业务闭环的原生安装规格。

### 2.1 `install_order`

明确安装顺序：

1. 启用高级权限
2. 补齐任务收集表单
3. 创建自动化与消息分发 scaffold
4. 创建路由与责任工作流
5. 创建管理仪表盘与异常雷达
6. 创建角色与权限工作面

### 2.2 `command_packs`

按原生对象分 pack 输出 `lark-cli base` 命令模板：

- `advperm`
- `form`
- `automation`
- `workflow`
- `dashboard`
- `role`

其中：

- `automation` pack 已经拆成 5 条自动化 scaffold
  - A1 新任务入场提醒
  - A2 分析完成自动汇报
  - A3 执行任务自动创建
  - A4 复核提醒
  - A5 异常升级提醒
- `workflow` pack 已经拆成 3 条责任工作流
  - W1 路由总分发工作流
  - W2 拍板分支工作流
  - W3 执行分支工作流
- `dashboard` pack 已经围绕管理汇报、证据评审、异常压盘组织 block 级蓝图
- `role` pack 已经带上 `dashboard_rule_map`、`view_rule`、`edit/read` 差异

### 2.3 `markdown`

直接可复制到飞书文档 / Wiki / 交接文档的原生安装说明。

---

## 3. `native-manifest/apply` 现在能做什么

除了返回安装包，现在还支持直接执行：

- `POST /api/v1/workflow/native-manifest/apply`
- 或 setup 时传 `apply_native=true`

执行范围支持：

- `form`
- `automation`
- `workflow`
- `dashboard`
- `role`

前端现在也支持按 surface 选择本次 apply 范围，而不是只能全量硬推。

执行结果会同时沉淀到两处：

1. API 状态里的 `native_apply_report`
2. Base 内 `自动化日志` 表，触发来源为 `native_manifest.apply`

这意味着“原生安装本身”已经开始被写回多维表格，而不只是存在本地进程内存里。

---

## 4. 当前原生化深度

### 已真实创建

- Base 本体
- 12 张业务表
- 多数业务视图
- 表单视图
- `apply_native` 成功时可创建表单 / 自动化 / 工作流 / 仪表盘 / 角色对象

### 已升级为更强业务 scaffold

自动化和工作流现在不只是“发一条空消息”，而是已经带上：

- 主表状态回写
- 当前责任角色切换
- 当前原生动作切换
- 自动化执行状态回写
- 交付动作 / 自动化日志沉淀
- 管理汇报 / 执行 / 复核 / 异常升级等业务语义

角色 scaffold 现在也不只是表级只读：

- 带 `dashboard_rule_map`
- 带 `view_rule.visibility`
- 区分高管 / 执行 / 复核三种工作面
- 执行 / 复核工作面支持 `edit`

仪表盘 scaffold 也从“一个统计卡”升级成了更像汇报页面的组合：

- 任务总量
- 待拍板 / 待执行 / 待复核
- 路由分布
- 业务归属分布
- 证据等级 / 评审动作
- 异常类型 / 归档状态

### 仍然存在的边界

以下事项仍需要真实飞书租户权限和成员配置才能最终闭环：

- 真实成员 / OpenID 映射
- 消息接收人、审批人、执行人绑定
- 工作流里更深的审批 / 任务 / AI 节点
- 仪表盘最终排版
- 角色成员分配

因此现在的准确口径是：

- 已完成“代码级原生安装能力 + scaffold 执行链路”
- 未完成“你租户权限下的真实飞书全链路联调验收”

---

## 5. 推荐落地顺序

1. 先 setup，确认 12 张表、主表字段契约、视图和模板中心都已建好
2. 启用高级权限
3. 确认 `📥 需求收集表` 的共享状态
4. 先 apply `automation + workflow`
5. 再 apply `dashboard + role`
6. 最后在 `自动化日志` 表里检查 `native_manifest.apply` 的逐项结果

---

## 6. 目标

最终目标不是让这个仓库永远替飞书做 UI 操作，而是形成稳定分工：

1. Python / Agent 负责生成分析结果、字段契约、业务信号和原生安装 scaffold。
2. 飞书多维表格原生对象负责真正的交付、分发、汇报、权限和可视化。
3. 前端只做驾驶舱、验收面和状态汇总，不替代飞书原生交付层。
