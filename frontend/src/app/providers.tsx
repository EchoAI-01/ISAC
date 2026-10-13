import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { AuthProvider } from "@/auth/AuthProvider";
import { ToastProvider } from "@/components/Toast";
import { shouldRetry } from "@/hooks/queries";

/**
 * 全局 Provider 组合。
 *
 * QueryClient 默认值针对控制面调优:
 * - 不自动重试 4xx (权限/未挂载是确定性结果, 重试只会延迟状态渲染);
 * - 窗口重聚焦时刷新 (运维页面长期挂着, 需要跟上后端变化);
 * - gcTime 5min: 十域间来回切换不重复打请求, 又不会长期持有陈旧敏感数据。
 */
export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: shouldRetry,
            staleTime: 10_000,
            gcTime: 300_000,
            refetchOnWindowFocus: true,
            refetchOnReconnect: true,
          },
          mutations: {
            retry: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>{children}</AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
