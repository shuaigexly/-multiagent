# 多维表格内嵌工作流面板

## 当前承载方式

不再以独立 `/workflow` 页面作为目标承载。

现在仓库已经新增多维表格扩展脚本入口：

- 构建入口：`bitable.html`
- 前端入口：`src/bitable-main.tsx`
- 插件面板：`src/pages/BitableWorkflowPlugin.tsx`

## 构建

```bash
cd frontend
npm run build:bitable
```

构建产物里会包含：

- `dist/bitable.html`
- 对应的 `dist/assets/bitable-*.js`

## 接入飞书多维表格

按飞书多维表格扩展脚本能力，把部署后的 `bitable.html` URL 配到 Base 的脚本入口。

预期使用方式：

1. 在多维表格中打开 `分析任务` 表
2. 选中一条任务记录
3. 扩展脚本内嵌面板自动读取当前选中记录并展示 workflow 轨道

## 当前能力范围

- 跟随当前选中的 `分析任务` 记录切换
- 直接读取 Base 内的任务/评审/动作/归档表数据
- 如果同域 localStorage 已存在 API Key，则额外订阅后端 SSE 实时事件流

## 说明

当前独立站点前端仍保留在仓库中，但对“多维表格内嵌工作流面板”这个目标来说，新的 `bitable.html` 才是后续主承载入口。
