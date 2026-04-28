import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

function resolveVendorChunk(id: string): string | undefined {
  if (!id.includes("/node_modules/")) return undefined;
  if (id.includes("/node_modules/@lark-base-open/js-sdk/")) {
    if (id.includes("/dist/RenderMarkDown-")) return "vendor-lark-markdown";
    if (id.includes("/dist/chunk-L3XSIM3S")) return "vendor-lark-core";
    if (id.includes("/dist/chunk-RXRZ2MSP")) return "vendor-lark-ui";
    if (id.includes("/dist/chunk-M2SGL6KA")) return "vendor-lark-bridge";
    return "vendor-lark-sdk";
  }
  if (
    id.includes("/node_modules/react/") ||
    id.includes("/node_modules/react-dom/") ||
    id.includes("/node_modules/scheduler/")
  ) {
    return "vendor-react";
  }
  if (id.includes("/node_modules/lucide-react/")) return "vendor-icons";
  if (id.includes("/node_modules/@radix-ui/")) return "vendor-radix";
  if (
    id.includes("/node_modules/react-markdown/") ||
    id.includes("/node_modules/remark-gfm/") ||
    id.includes("/node_modules/mdast-") ||
    id.includes("/node_modules/micromark") ||
    id.includes("/node_modules/unified/") ||
    id.includes("/node_modules/unist-") ||
    id.includes("/node_modules/hast-") ||
    id.includes("/node_modules/remark-") ||
    id.includes("/node_modules/rehype-")
  ) {
    return "vendor-markdown";
  }
  if (
    id.includes("/node_modules/class-variance-authority/") ||
    id.includes("/node_modules/clsx/") ||
    id.includes("/node_modules/tailwind-merge/") ||
    id.includes("/node_modules/@floating-ui/") ||
    id.includes("/node_modules/cmdk/") ||
    id.includes("/node_modules/embla-carousel-react/") ||
    id.includes("/node_modules/input-otp/") ||
    id.includes("/node_modules/next-themes/") ||
    id.includes("/node_modules/sonner/") ||
    id.includes("/node_modules/vaul/")
  ) {
    return "vendor-ui";
  }
  if (
    id.includes("/node_modules/recharts/") ||
    id.includes("/node_modules/d3-") ||
    id.includes("/node_modules/victory-vendor/")
  ) {
    return "vendor-charts";
  }
  if (id.includes("/node_modules/react-router/") || id.includes("/node_modules/react-router-dom/")) {
    return "vendor-router";
  }
  if (
    id.includes("/node_modules/react-hook-form/") ||
    id.includes("/node_modules/@hookform/") ||
    id.includes("/node_modules/react-day-picker/")
  ) {
    return "vendor-forms";
  }
  if (id.includes("/node_modules/@sentry/")) {
    return "vendor-monitoring";
  }
  if (
    id.includes("/node_modules/axios/") ||
    id.includes("/node_modules/zod/") ||
    id.includes("/node_modules/date-fns/") ||
    id.includes("/node_modules/@tanstack/")
  ) {
    return "vendor-data";
  }
  return "vendor-misc";
}

export default defineConfig(({ mode }) => {
  const bitableOnly = mode === "bitable";
  // v8.6.20-r15：GitHub Pages 部署 — 仓库名 `-multiagent` → 资源路径 /-multiagent/
  // PUBLIC_BASE_PATH=/-multiagent/ 由 GitHub Actions workflow 注入；本地 build 默认 "/"
  const publicBase = process.env.PUBLIC_BASE_PATH || "/";

  return {
    base: publicBase,
    server: {
      host: "::",
      port: 8080,
      hmr: {
        overlay: false,
      },
    },
    plugins: [react()],
    build: {
      chunkSizeWarningLimit: 800,
      rollupOptions: {
        input: bitableOnly
          ? {
              bitable: path.resolve(__dirname, "bitable.html"),
            }
          : {
              main: path.resolve(__dirname, "index.html"),
              bitable: path.resolve(__dirname, "bitable.html"),
            },
        output: {
          manualChunks(id) {
            return resolveVendorChunk(id);
          },
        },
      },
    },
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
      dedupe: ["react", "react-dom", "react/jsx-runtime", "react/jsx-dev-runtime", "@tanstack/react-query", "@tanstack/query-core"],
    },
  };
});
