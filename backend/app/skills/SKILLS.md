# Agent Skills 索引

本目录存放智能体技能文件。智能体启动分析前先读此索引，按需加载匹配自身角色的技能。

## 使用规则
- `tags: [all]` 表示所有智能体均应加载
- `tags: [agent_id, ...]` 表示仅该角色加载
- `priority: high` 的技能内容将优先注入

## 技能清单

| skill_id | file | tags | priority | description |
|----------|------|------|----------|-------------|
| pyramid_principle | pyramid_principle.md | all | high | 金字塔原则：结论先行、MECE、So What?测试 |
| feishu_context_usage | feishu_context_usage.md | all | high | 飞书上下文深度利用：日历/任务/文档三类数据提取规则 |
| data_analysis_methods | data_analysis_methods.md | data_analyst,finance_advisor | high | 数据分析方法论：指标拆解、归因分析、异常检测 |
| financial_analysis | financial_analysis.md | finance_advisor | normal | 财务分析技能：健康指标、现金流、成本结构诊断 |
| product_thinking | product_thinking.md | product_manager | normal | 产品思维：ICE优先级、用户价值、路线图决策框架 |
| seo_growth | seo_growth.md | seo_advisor | normal | SEO增长技能：关键词机会评估、流量结构分析框架 |
| content_strategy | content_strategy.md | content_manager | normal | 内容策略技能：内容资产盘点、复用框架、缺口识别 |
| executive_summary | executive_summary.md | ceo_assistant | high | 管理层摘要写法：信号萃取、跨模块决策优先级排序 |
