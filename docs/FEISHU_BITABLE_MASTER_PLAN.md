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
7. CEO 报告增强字段
8. 主表交付快照字段
9. 工作流路由字段
10. 工作流消息包 / 执行包
11. 自动生成跟进任务
12. 自动生成复核任务
13. 前端驾驶舱增强

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
- 背景说明
- 目标对象
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

### 5.7 管理确认

- 是否已拍板
- 拍板人
- 拍板时间
- 是否已执行落地
- 执行完成时间
- 是否进入复盘

---

## 6. 当前缺口清单

下面这些不是可选项，而是离“完整系统”仍然差的部分。

### P0 缺口

1. `复核历史` 表未实装
2. `交付结果归档` 表未实装
3. 主表 owner / SLA / 拍板字段未实装
4. 版本链未实装
5. 飞书原生工作流未真正接进主链路

### P1 缺口

1. `自动化日志` 表未实装
2. 仪表盘未迁回飞书原生为主
3. 表单模板未分场景
4. 模板配置中心未实装
5. 权限模型未角色化落地

### P2 缺口

1. 多 Base 策略未产品化
2. schema migration 未做
3. AI 工作流节点未深度接入
4. 群消息触发型工作流未实装

---

## 7. 一次性完整规划

### Phase 1 基础闭环补全

目标：

- 让系统不只会分析，还能保留复核和结果归档。

交付项：

1. 新增 `复核历史`
2. 新增 `交付结果归档`
3. 主表新增 owner / SLA / 拍板字段
4. 动作表新增失败归因
5. 重跑版本号链路

### Phase 2 原生工作流接管

目标：

- 让多维表格自动化 / 工作流正式进入主链路。

交付项：

1. 配置路由总分发工作流
2. 配置汇报 / 执行 / 复核 / 重跑分支
3. 配置失败补救工作流
4. 配置超时提醒
5. 配置自动化日志回写

### Phase 3 原生汇报体系

目标：

- 让飞书内就能看、就能汇报、就能追。

交付项：

1. 高管仪表盘
2. 交付运营仪表盘
3. 复核中心仪表盘
4. 证据质量仪表盘
5. 数据资产健康仪表盘

### Phase 4 入口与模板化

目标：

- 让不同业务场景标准化进入系统。

交付项：

1. 四套任务表单
2. 模板配置中心
3. 汇报模板
4. 执行模板
5. 复核模板
6. 归档模板

### Phase 5 权限与规模化

目标：

- 让系统从单 demo 进化为可持续业务系统。

交付项：

1. 角色化权限方案
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
