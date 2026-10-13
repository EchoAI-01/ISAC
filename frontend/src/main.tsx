import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { AppProviders } from "@/app/providers";
import { router } from "@/app/router";
import { applyTheme, readTheme } from "@/lib/theme";

import "@/styles/tokens.css";
import "@/styles/base.css";
import "@/styles/components.css";

// 主题: index.html 内联脚本已在首帧前设置, 这里再对齐一次 (含 auto 解析)。
applyTheme(readTheme());

const container = document.getElementById("root");
if (!container) {
  throw new Error("挂载点 #root 缺失 (index.html 被改坏?)");
}

createRoot(container).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
);
