import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// 后端控制面地址 (FE1: 生产推荐同源反代; 开发态用 Vite proxy 保持同源语义,
// 使 Session Cookie / CSRF 双提交 / SSE 全部按同源工作, 无需配置 control.cors)。
// 需要连远端实例时: ISAC_API_TARGET=http://host:8765 npm run dev
const apiTarget = process.env.ISAC_API_TARGET ?? "http://127.0.0.1:8765";

// SSE (text/event-stream) 经代理时必须关闭缓冲, 否则实时日志台/事件流会攒批不下发。
const sseProxy = {
  target: apiTarget,
  changeOrigin: true,
  // http-proxy 默认流式转发; 显式关闭自处理响应, 避免代理侧缓冲。
  selfHandleResponse: false,
  proxyTimeout: 0,
  timeout: 0,
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: Number(process.env.ISAC_WEB_PORT ?? 5173),
    strictPort: false,
    proxy: {
      "/api": sseProxy,
      "/health": sseProxy,
      "/metrics": sseProxy,
    },
  },
  preview: {
    port: Number(process.env.ISAC_WEB_PREVIEW_PORT ?? 4173),
    proxy: {
      "/api": sseProxy,
      "/health": sseProxy,
      "/metrics": sseProxy,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", "dist", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/api/openapi.d.ts", "src/test/**", "src/**/*.d.ts", "src/main.tsx"],
    },
  },
});
