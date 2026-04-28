import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  const bitableOnly = mode === "bitable";

  return {
    server: {
      host: "::",
      port: 8080,
      hmr: {
        overlay: false,
      },
    },
    plugins: [react()],
    build: {
      rollupOptions: {
        input: bitableOnly
          ? {
              bitable: path.resolve(__dirname, "bitable.html"),
            }
          : {
              main: path.resolve(__dirname, "index.html"),
              bitable: path.resolve(__dirname, "bitable.html"),
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
