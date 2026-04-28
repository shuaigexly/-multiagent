#!/usr/bin/env node
/**
 * v8.6.20-r17：按飞书数据表视图扩展开发指南打 zip 包
 * https://open.feishu.cn/document/base-extensions/base-table-view-extension-development-guide
 *
 * 关键要求：
 * - dist/ 根必须含 index.html（入口）—— 我们的 bitable.html 要复制成 index.html
 * - dist/ 根必须含 block.json（含 blockTypeID）
 * - dist/ 根必须含 app.json（含 appId，飞书后台注入）
 * - 所有资源用相对路径（./assets/...）
 *
 * 用法：
 *   cd frontend
 *   PUBLIC_BASE_PATH=./ npm run build    # 相对路径产物
 *   node package-plugin.mjs              # 输出 lark-multiagent-plugin.zip
 */
import { createWriteStream, existsSync, copyFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(__dirname, "dist");
const OUT_ZIP = path.join(__dirname, "lark-multiagent-plugin.zip");

if (!existsSync(DIST)) {
  console.error(`✗ ${DIST} 不存在 — 先跑 npm run build`);
  process.exit(1);
}
if (!existsSync(path.join(DIST, "index.json"))) {
  console.error(`✗ ${DIST}/index.json 不存在 — 确认 public/index.json 存在并重新 build`);
  process.exit(1);
}
if (!existsSync(path.join(DIST, "project.config.json"))) {
  console.error(`✗ ${DIST}/project.config.json 不存在 — 确认 public/project.config.json 存在并重新 build`);
  process.exit(1);
}
// v8.6.20-r17：飞书要 dist/index.html 入口，我们 vite 输出的 bitable.html 复制为 index.html
const BITABLE_HTML = path.join(DIST, "bitable.html");
const INDEX_HTML = path.join(DIST, "index.html");
if (existsSync(BITABLE_HTML)) {
  copyFileSync(BITABLE_HTML, INDEX_HTML);
  console.log("ℹ 已把 bitable.html 复制为 index.html（飞书插件入口）");
} else if (!existsSync(INDEX_HTML)) {
  console.error(`✗ ${BITABLE_HTML} 和 ${INDEX_HTML} 都不存在`);
  process.exit(1);
}

// 用 archiver（如果没装则降级到内置 zlib + 简易 zip）
let archiver;
try {
  archiver = (await import("archiver")).default;
} catch {
  console.log("ℹ archiver 未安装，npm install archiver --no-save 中…");
  const { execSync } = await import("node:child_process");
  execSync("npm install archiver --no-save --no-audit --no-fund", { stdio: "inherit", cwd: __dirname });
  archiver = (await import("archiver")).default;
}

const output = createWriteStream(OUT_ZIP);
const archive = archiver("zip", { zlib: { level: 9 } });

output.on("close", () => {
  const sizeKb = (archive.pointer() / 1024).toFixed(1);
  console.log(`\n✓ 打包成功`);
  console.log(`  路径: ${OUT_ZIP}`);
  console.log(`  大小: ${sizeKb} KB`);
  console.log(`\n下一步：`);
  console.log(`  1. 在飞书开放平台「多维表格数据表视图」配置页`);
  console.log(`  2. 点「小组件版本」下拉旁的"上传新版本"，选这个 zip`);
  console.log(`  3. 上传成功后该下拉会出现版本号；选 v1.0.0 即可`);
  console.log(`  4. 「更新类型」选「全量更新」（首次发布）`);
});
archive.on("warning", (err) => console.warn("warn:", err));
archive.on("error", (err) => { throw err; });

archive.pipe(output);
archive.directory(DIST, false);
await archive.finalize();
