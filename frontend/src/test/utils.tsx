import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

import { ToastProvider } from "@/components/Toast";
import { session } from "@/api/session";

/** 每个用例一个全新的 QueryClient (禁用重试, 让断言确定性)。 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
}

export interface TestRenderOptions extends Omit<RenderOptions, "wrapper"> {
  route?: string;
  queryClient?: QueryClient;
}

/** 带 Query + Router + Toast 的渲染包装 (页面测试统一入口)。 */
export function renderWithProviders(ui: ReactElement, options: TestRenderOptions = {}) {
  const queryClient = options.queryClient ?? makeQueryClient();
  const route = options.route ?? "/";

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <ToastProvider>{children}</ToastProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }

  return { queryClient, ...render(ui, { wrapper: Wrapper, ...options }) };
}

/** 构造一个 Response (fetch mock 用)。 */
export function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

/** 统一错误体 (CONTROL_PLANE_SPEC §3.6)。 */
export function errorBody(code: string, message: string, extra: Record<string, unknown> = {}) {
  return { detail: { code, message, ...extra } };
}

/** 把会话置为已认证的 Bearer 轨 (页面测试跳过登录流程)。 */
export function loginAsBearer(token = "test-token"): void {
  session.markBearerSession(token);
}

/** 把会话置为 Cookie 轨。 */
export function loginAsCookie(): void {
  session.markCookieSession();
}

export function logoutSession(): void {
  session.clear();
}

/** 等待若干微任务/宏任务轮次 (让 Query 的 promise 链落地)。 */
export async function flush(times = 3): Promise<void> {
  for (let index = 0; index < times; index += 1) {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}
