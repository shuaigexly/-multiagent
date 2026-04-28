# 多维表格内嵌工作流面板

## 当前承载方式

不再以独立 `/workflow` 页面作为目标承载。

仓库当前已经按飞书多维表格扩展脚本模式收口。`frontend/node_modules/@lark-base-open/js-sdk/README.md` 明确说明这个 SDK 是给“多维表格扩展脚本”使用的，详细 API 文档入口是：

- `https://lark-base-team.github.io/js-sdk-docs/zh/`

现在仓库已经新增多维表格扩展脚本入口：

- 构建入口：`bitable.html`
- 前端入口：`src/bitable-main.tsx`
- 插件面板：`src/pages/BitableWorkflowPlugin.tsx`

`/workflow` 路由现在只保留迁移说明，不再作为真实工作流执行界面。

## 构建

```bash
cd frontend
npm run build:bitable
```

这个命令只产出多维表格脚本入口。

构建产物里至少会包含：

- `dist/bitable.html`
- 对应的 `dist/assets/bitable-*.js`

## 接入飞书多维表格

按飞书多维表格扩展脚本能力，把部署后的 `bitable.html` URL 配到 Base 的扩展脚本入口。

预期使用方式：

1. 部署 `dist/bitable.html`
2. 在多维表格里新增扩展脚本，并填入这个部署地址
3. 在多维表格中打开 `分析任务 / 产出评审 / 交付动作 / 交付结果归档` 任一工作流表
4. 选中一条相关记录
5. 右侧扩展脚本面板自动读取当前选中记录并展示 workflow 轨道

## 当前能力范围

- 跟随当前选中的 `分析任务 / 产出评审 / 交付动作 / 交付结果归档` 记录切换
- 优先通过 `关联记录ID` 回溯主任务，缺失时退回 `任务标题` 做逻辑关联
- 直接读取 Base 内的任务/评审/动作/归档表数据
- 如果同域 localStorage 已存在 API Key，则额外订阅后端 SSE 实时事件流

## 说明

当前独立站点前端仍保留在仓库中，但对“多维表格内嵌工作流面板”这个目标来说，`bitable.html` 才是唯一主承载入口。
