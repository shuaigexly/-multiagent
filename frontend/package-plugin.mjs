#!/usr/bin/env node
/**
 * v8.6.20-r16：把 frontend/dist/ 打成飞书 Bitable 小组件 zip 包。
 *
 * 飞书数据表视图插件要求：所有 HTML/JS/CSS/img 静态资源 + 一个 manifest.json
 * 一起 zip，由开发者后台上传得到「小组件版本号」。我们这里把构建产物 dist/
 * 里的所有文件 + dist/manifest.json（vite 自动从 public/ 拷贝）打成
 * `lark-multiagent-plugin.zip`，用户在飞书开发者后台上传即可。
 *
 * 用法：
 *   cd frontend
 *   PUBLIC_BASE_PATH=./ npm run build      # 关键：用相对路径，飞书 zip 不允许绝对 URL
 *   node package-plugin.mjs                # 输出 lark-multiagent-plugin.zip
 */
import { createWriteStream, existsSync, statSync, readdirSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DIST = path.join(__dirname, "dist");
const OUT_ZIP = path.join(__dirname, "lark-multiagent-plugin.zip");

if (!existsSync(DIST)) {
  console.error(`✗ ${DIST} 不存在 — 先跑 npm run build`);
  process.exit(1);
}
if (!existsSync(path.join(DIST, "manifest.json"))) {
  console.error(`✗ ${DIST}/manifest.json 不存在 — 确认 public/manifest.json 存在并重新 build`);
  process.exit(1);
}
if (!existsSync(path.join(DIST, "bitable.html"))) {
  console.error(`✗ ${DIST}/bitable.html 不存在 — 确认 vite build 输出了 bitable.html 入口`);
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
