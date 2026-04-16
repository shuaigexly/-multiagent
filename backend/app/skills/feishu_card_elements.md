---
skill_id: feishu_card_elements
name: 飞书消息卡片元素规范
description: lark_md语法、卡片元素tag、@提及格式、模板色彩选择规则
tags: [all]
priority: high
---

# 飞书消息卡片元素规范

## lark_md 支持的语法

| 效果 | 语法 |
|------|------|
| **加粗** | `**文字**` |
| *斜体* | `*文字*` |
| ~~删除线~~ | `~~文字~~` |
| `代码` | `` `代码` `` |
| [链接](url) | `[显示文字](URL)` |
| 引用块 | `> 引用内容` |
| 无序列表 | `- 条目` |
| 有序列表 | `1. 条目` |
| 任务列表 | `- [ ] 未完成` / `- [x] 已完成` |

### @提及语法
```
<at user_id="ou_xxxxxxxxxxxxxxxx">张三</at>
```
- 必须填写真实 open_id，不得伪造
- @所有人：`<at user_id="all">所有人</at>`

### 不支持（禁止使用）
- Markdown 表格语法（改用多行 div 文字）
- HTML 标签
- 图片语法 `![](url)`

## 卡片元素 tag 类型（schema 2.0）

```json
// 文本块（最常用）
{"tag": "div", "text": {"tag": "lark_md", "content": "**标题**\n正文内容"}}

// 分割线
{"tag": "hr"}

// 灰色备注
{"tag": "note", "elements": [{"tag": "plain_text", "content": "备注文字"}]}

// 按钮行动区
{"tag": "action", "actions": [
  {"tag": "button", "text": {"tag": "plain_text", "content": "查看报告"},
   "type": "primary", "url": "https://..."}
]}

// 两列布局
{"tag": "column_set", "flex_mode": "bisect", "columns": [
  {"tag": "column", "elements": [...]},
  {"tag": "column", "elements": [...]}
]}
```

## Header 模板颜色选择
| 情境 | 颜色 | template 值 |
|------|------|------------|
| 风险/告警 | 红色 | `red` |
| 达成/好消息 | 绿色 | `green` |
| 普通报告 | 蓝色 | `blue` |
| 警示/关注 | 橙色 | `orange` |
| 任务/执行 | 黄色 | `yellow` |
| 高管摘要 | 靛蓝 | `indigo` |

## 内容长度限制
- 单个 div content：建议 ≤ 500 字，绝对上限 3000 字
- 整张卡片 elements 数量：建议 ≤ 15 个
- 卡片标题 (header.title)：≤ 30 字

## 最佳实践
1. 第一个 element 放"一句话核心结论"（加粗）
2. 用 `hr` 分隔不同模块内容
3. 行动建议用 `- [ ]` 任务格式，飞书可一键转任务
4. 末尾加 button 链接到完整报告页面
5. 避免纯数字堆砌，数字旁边必须有对比基准和方向箭头
