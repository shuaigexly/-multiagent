# 飞书多维表格多 Agent 交付闭环总规划

本文档是仓库内关于“飞书多维表格原生交付闭环”的唯一总规划入口。

如果只看一份文档，就看这一份。

它解决 5 个问题：

1. 当前系统已经做到什么。
2. 最终目标态到底是什么。
3. 还缺哪些能力。
4. 应该按什么顺序做。
5. 什么叫做真正做完。

---

## 1. 一句话定义

这不是一个“接了七个 Agent 的分析 demo”。

这套系统的目标定义应当是：

一个以飞书多维表格为主载体的多 Agent 交付操作系统，能够完成任务 intake、分析生产、证据治理、评审路由、原生工作流执行、复核闭环、结果归档与管理汇报。

---

## 2. 当前已完成

### 2.1 已实装到代码

1. 七岗多 Agent 分析流水线
2. 主任务表状态机
3. 数据源库引用
4. 证据链表
5. 产出评审表
6. 交付动作表
7. 复核历史表
8. 自动化日志表
9. 交付结果归档表
10. 模板配置中心
11. CEO 报告增强字段
12. 主表交付快照字段
13. 工作流路由字段
14. 工作流消息包 / 执行包
15. 管理确认字段（拍板 / 执行完成 / 进入复盘）
16. 原生蓝图状态刷新与安装报告
17. `native_manifest/apply` 原生安装执行链路
18. 前端驾驶舱增强

### 2.2 已完成的设计文档

1. [FEISHU_BITABLE_OFFICIAL_ALIGNMENT.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_OFFICIAL_ALIGNMENT.md)
2. [FEISHU_BITABLE_NATIVE_PLAYBOOK.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_NATIVE_PLAYBOOK.md)
3. [FEISHU_BITABLE_CAPABILITY_BACKLOG.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_CAPABILITY_BACKLOG.md)
4. [FEISHU_BITABLE_DELIVERY_SYSTEM_BLUEPRINT.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_DELIVERY_SYSTEM_BLUEPRINT.md)
5. [FEISHU_BITABLE_AUTOMATION_WORKFLOW_LIBRARY.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_AUTOMATION_WORKFLOW_LIBRARY.md)
6. [FEISHU_BITABLE_VALIDATION_BOUNDARY.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_VALIDATION_BOUNDARY.md)

---

## 3. 最终目标态

最终目标态分成 8 层。

### 3.1 入口层

- 表单入口
- 主表手工录入入口
- 模板化任务入口
- 群消息触发入口
- `setup mode` 区分模板 / 生产 / 验证 Base

### 3.2 分析生产层

- 七岗 Agent
- 数据资产引用
- 图像/附件输入
- 分阶段分析与缓存恢复

### 3.3 证据治理层

- 证据链
- 证据等级
- 证据置信度
- 证据用途
- 证据复核

### 3.4 结论评审层

- 自动评审
- 真实性
- 决策性
- 可执行性
- 闭环准备度

### 3.5 路由决策层

- 直接汇报
- 等待拍板
- 直接执行
- 补数复核
- 重新分析

### 3.6 原生工作流层

- 自动化
- 工作流
- AI 文本节点
- 审批 / 消息 / 任务 / 提醒

### 3.7 交付闭环层

- 交付动作
- 复核历史
- 自动化日志
- 交付结果归档

### 3.8 管理汇报层

- 高管一页纸
- 仪表盘
- 角色视图
- 前端驾驶舱

---

## 4. 目标态表结构

目标态应为 12 表。

### 4.1 已实现

1. `分析任务`
2. `岗位分析`
3. `综合报告`
4. `数字员工效能`
5. `📚 数据源库`
6. `证据链`
7. `产出评审`
8. `交付动作`
9. `复核历史`
10. `自动化日志`
11. `交付结果归档`
12. `模板配置中心`

### 4.2 验收状态说明

表结构“已实现”不等于“真实飞书联调已完成”。

当前正确理解是：

1. 代码内的 12 表目标结构已经进入主链路
2. 本地测试已验证这些表相关的字段、回填和调度逻辑
3. 是否已经在真实飞书环境成功创建、写入、更新，还必须单独做线上联调

真实联调边界与通过标准，统一见：

- [FEISHU_BITABLE_VALIDATION_BOUNDARY.md](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_VALIDATION_BOUNDARY.md)

---

## 5. 主表目标字段模型

主表最终应包含 7 组字段。

### 5.1 任务输入

- 任务标题
- 分析维度
- 优先级
- 任务来源
- 业务归属
- 背景说明
- 目标对象
- 汇报对象级别
- 输出目的
- 成功标准
- 约束条件
- 业务阶段
- 引用数据集
- 数据源
- 任务图像

### 5.2 调度状态

- 状态
- 当前阶段
- 进度
- 任务编号
- 依赖任务编号
- 创建时间
- 最近更新
- 完成日期

### 5.3 证据快照

- 证据条数
- 高置信证据数
- 硬证据数
- 待验证证据数
- 进入CEO汇总证据数
- 决策事项数
- 需补数条数

### 5.4 结论快照

- 最新评审动作
- 最新评审摘要
- 最新管理摘要
- 汇报就绪度
- 结论稳定性
- 数据口径状态

### 5.5 工作流契约

- 工作流路由
- 工作流消息包
- 工作流执行包
- 待发送汇报
- 待创建执行任务
- 待安排复核
- 建议复核时间

### 5.6 交付管理

- 汇报对象
- 汇报版本号
- 执行 owner
- 执行截止时间
- 复核 owner
- 复核 SLA
- 归档状态
- 自动化执行状态

### 5.7 管理确认

- 是否已拍板
- 拍板人
- 拍板时间
- 是否已执行落地
- 执行完成时间
- 是否进入复盘

---

## 6. 当前剩余缺口

下面这些仍然是离“真实飞书租户全闭环”差的部分，但它们已经不再是“代码里完全没有”。

### P0 联调缺口

1. 真实成员 / OpenID 映射仍需按租户补齐
2. 工作流中的审批人、执行人、消息接收人仍需真实绑定
3. 多维表格云侧自动化 / 工作流 / 仪表盘 / 角色仍需在真实租户完成联调验收
4. 真实飞书写入权限和租户 scope 仍需逐项校验

### P1 产品化缺口

1. 多 Base 策略仍偏工程化，尚未做成更稳定的产品入口
2. schema migration 与历史 Base 升级策略仍需补齐
3. 模板中心还可以继续做行业 / 场景化模板分层
4. 仪表盘视觉排版和汇报材料风格仍可继续增强

### P2 深化能力缺口

1. AI 工作流节点仍可继续前推到更深的飞书原生工作流里
2. 群消息驱动工作流仍依赖外部命令解析写回
3. 固定时段管理播报、审批升级、异常治理链路仍可继续细化
4. 更完整的版本链与变更追踪仍可继续增强

---

## 7. 一次性完整规划

### Phase 1 真实联调闭环

目标：

- 让当前代码能力在真实飞书租户里完全跑通。

交付项：

1. 补齐真实成员 / OpenID / chat_id 绑定
2. 验证 `automation / workflow / dashboard / role` 全量 apply
3. 校验真实飞书写入、回写、状态切换、日志沉淀
4. 验证 `交付动作 / 自动化日志 / 交付结果归档` 三条审计链
5. 固化线上验收用例和回归清单

### Phase 2 原生工作流深化

目标：

- 让飞书原生自动化 / 工作流承担更多后半段执行责任。

交付项：

1. 继续深化审批 / AI 节点 / 定时调度
2. 扩展异常补救、升级、重跑、群消息驱动
3. 细化角色责任面和 dashboard 运营动作
4. 扩展模板化安装包和蓝图升级能力
5. 强化主表字段契约与飞书原生动作的映射

### Phase 3 原生汇报体系

目标：

- 让飞书内就能看、就能汇报、就能追。

交付项：

1. 高管仪表盘
2. 交付运营仪表盘
3. 复核中心仪表盘
4. 证据质量仪表盘
5. 数据资产健康仪表盘

### Phase 4 入口与模板化深化

目标：

- 让不同业务场景标准化进入系统。

交付项：

1. 四套任务表单
2. 模板配置中心的场景化扩充
3. 汇报模板
4. 执行模板
5. 复核模板
6. 归档模板

### Phase 5 权限与规模化

目标：

- 让系统从单 demo 进化为可持续业务系统。

交付项：

1. 角色化权限方案深化
2. 多 Base 模式
3. 模板 Base / 生产 Base / 验证 Base
4. schema 版本升级策略

---

## 8. 文档之间的关系

如果要查不同维度，入口如下：

- 总规划：本文件
- 官方边界：[`FEISHU_BITABLE_OFFICIAL_ALIGNMENT.md`](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_OFFICIAL_ALIGNMENT.md)
- 原生使用原则：[`FEISHU_BITABLE_NATIVE_PLAYBOOK.md`](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_NATIVE_PLAYBOOK.md)
- 详细缺口池：[`FEISHU_BITABLE_CAPABILITY_BACKLOG.md`](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_CAPABILITY_BACKLOG.md)
- 目标态蓝图：[`FEISHU_BITABLE_DELIVERY_SYSTEM_BLUEPRINT.md`](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_DELIVERY_SYSTEM_BLUEPRINT.md)
- 自动化/工作流模板：[`FEISHU_BITABLE_AUTOMATION_WORKFLOW_LIBRARY.md`](/Users/jassionyang/-multiagent/docs/FEISHU_BITABLE_AUTOMATION_WORKFLOW_LIBRARY.md)

---

## 9. 做完的判断标准

只有满足下面这些条件，才可以说“规划和系统都完整了”：

1. 任务可从表单或主表进入。
2. 数据可从数据源库复用。
3. 七岗输出可被结构化沉淀。
4. 证据可独立治理。
5. 评审可决定是否交付。
6. 路由可决定是否汇报 / 执行 / 复核 / 重跑。
7. 飞书原生自动化和工作流真正接手后续动作。
8. 动作表能看清交付过程。
9. 复核历史能看清结论变化。
10. 归档表能看清最终业务结果。
11. 仪表盘能服务高管和运营。
12. 前端不是唯一入口和唯一可视化。

---

## 10. 结论

前几轮我已经把很多内容写进仓库了，但确实没有先给你一份“单文档总规划”。

现在这份文档就是那个缺失的总入口。

如果后面继续开发，应该统一以本文件为主索引推进，而不是再零散地补小段说明。
