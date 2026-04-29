#!/usr/bin/env node
/**
 * v8.6.20-r17：按飞书数据表视图扩展开发指南打 zip 包
 * https://open.feishu.cn/document/base-extensions/base-table-view-extension-development-guide
 *
 * 关键要求：
 * - dist/ 根必须含 index.html（入口）—— 我们的 bitable.html 要复制成 index.html
 * - dist/ 根必须含 index.json（含 blockTypeID）
 * - dist/ 根必须含 project.config.json（含 appid / blocks）
 * - 所有资源用相对路径（./assets/...）
 *
 * 用法：
 *   cd frontend
 *   npm run build:plugin                 # 输出 lark-multiagent-plugin.zip
 */
import { createWriteStream, existsSync, copyFileSync, readFileSync, statSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
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

const indexHtml = readFileSync(INDEX_HTML, "utf8");
if (/\b(?:src|href)=["']\/(?!\/)/.test(indexHtml)) {
  console.error("✗ dist/index.html 含绝对资源路径。请用 npm run build:plugin 或 vite --mode bitable 生成相对路径产物。");
  process.exit(1);
}

function packageWithSystemZip() {
  if (existsSync(OUT_ZIP)) {
    unlinkSync(OUT_ZIP);
  }
  execFileSync("zip", ["-qr", OUT_ZIP, "."], { cwd: DIST, stdio: "inherit" });
  const sizeKb = (statSync(OUT_ZIP).size / 1024).toFixed(1);
  console.log(`\n✓ 打包成功`);
  console.log(`  路径: ${OUT_ZIP}`);
  console.log(`  大小: ${sizeKb} KB`);
}

// 用 archiver；若未安装则降级到系统 zip，不在打包脚本里临时 npm install。
let archiver;
try {
  archiver = (await import("archiver")).default;
} catch {
  try {
    console.log("ℹ archiver 未安装，改用系统 zip 命令打包");
    packageWithSystemZip();
    console.log(`\n下一步：`);
    console.log(`  1. 在飞书开放平台「多维表格数据表视图」配置页`);
    console.log(`  2. 点「小组件版本」下拉旁的"上传新版本"，选这个 zip`);
    console.log(`  3. 上传成功后该下拉会出现版本号；选 v1.0.0 即可`);
    console.log(`  4. 「更新类型」选「全量更新」（首次发布）`);
    process.exit(0);
  } catch (err) {
    console.error("✗ archiver 未安装，且系统 zip 命令不可用。请安装 archiver 依赖或提供 zip 命令。");
    console.error(err);
    process.exit(1);
  }
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
