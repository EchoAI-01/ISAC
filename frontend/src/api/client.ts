/** API 客户端 (契约驱动)。
 *
 * - `client` 是 openapi-fetch 实例, 泛型取自 `src/api/openapi.d.ts`
 *   (由 docs/api/openapi.json 生成, FE0 契约基线): **path / method / query /
 *   path 参数 / 请求体形状全部编译期校验**, 拼错端点或漏传参数直接编译失败。
 * - 响应体在契约里是宽松的 `{[key: string]: unknown}` (后端路由未声明
 *   response_model), 因此领域响应形状由 `src/api/types.ts` 显式建模, 并在
 *   `unwrap<T>()` 一处收敛断言 (端点模块不散落 `as`)。
 * - 认证双轨 (CONTROL_PLANE_SPEC §8.2 规则 5): 会话 Cookie + CSRF 双提交为主,
 *   Bearer 为降级轨 (后端未启用会话 Cookie 时 POST /auth/session 返回 404)。
 * - 401/428 由响应中间件广播给路由守卫 (跳登录 / 跳首登向导)。
 */

import createClient, { type Middleware } from "openapi-fetch";

import { ApiError, apiErrorFrom, networkError } from "./errors";
import type { paths } from "./openapi";
import { readCsrfToken, session } from "./session";

/**
 * API 基址。默认空串 = 同源 (开发态经 Vite proxy 转发到 127.0.0.1:8765,
 * 生产按 FE1 推荐同源反代)。跨源部署时构建期注入 VITE_ISAC_API_BASE,
 * 并在后端 control.cors.origins 放行该 origin (Cookie 轨需 allow_credentials=true)。
 */
export const API_BASE: string = (import.meta.env.VITE_ISAC_API_BASE as string | undefined) ?? "";

/** 跨源时必须 include 才会带 Cookie; 同源用 same-origin 即可。 */
const CROSS_ORIGIN = Boolean(API_BASE);

export const client = createClient<paths>({
  baseUrl: API_BASE,
  credentials: CROSS_ORIGIN ? "include" : "same-origin",
  headers: { Accept: "application/json" },
});

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** 构造认证头 (SSE 客户端等非 openapi-fetch 路径复用同一口径)。 */
export function authHeaders(method: string): Record<string, string> {
  const headers: Record<string, string> = {};
  const snapshot = session.get();
  if (snapshot.mode === "bearer" && snapshot.token) {
    headers.Authorization = `Bearer ${snapshot.token}`;
  }
  // 会话 Cookie 轨的写请求必须带双提交 CSRF 头 (后端 CSRFProtectionMiddleware)。
  if (snapshot.mode === "cookie" && UNSAFE_METHODS.has(method.toUpperCase())) {
    const csrf = readCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return headers;
}

/** 拼 URL (SSE / 下载等非 openapi-fetch 路径用)。 */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

const middleware: Middleware = {
  async onRequest({ request }) {
    for (const [key, value] of Object.entries(authHeaders(request.method))) {
      request.headers.set(key, value);
    }
    return request;
  },
  async onResponse({ response }) {
    // 全局认证信号: 401 → 登录页; 428 → 首登向导 (T3-backend gate)。
    if (response.status === 401) session.signal("unauthorized");
    else if (response.status === 428) session.signal("setup_required");
    return response;
  },
};

client.use(middleware);

/** openapi-fetch 的返回形状 (data / error / response)。 */
export interface FetchResult {
  data?: unknown;
  error?: unknown;
  response: Response;
}

async function readBodySafely(response: Response): Promise<unknown> {
  try {
    return await response.clone().json();
  } catch {
    try {
      const text = await response.clone().text();
      return text === "" ? null : text;
    } catch {
      return null;
    }
  }
}

/**
 * 解包 openapi-fetch 结果: 成功返回 `T`, 失败抛 `ApiError`。
 *
 * TanStack Query 期望"失败即 throw"; 页面据 `ApiError.kind` 渲染
 * permission-denied / unavailable / conflict / error 状态, 不散落状态码判断。
 */
export async function unwrap<T>(
  result: Promise<FetchResult> | FetchResult,
  path: string,
): Promise<T> {
  let resolved: FetchResult;
  try {
    resolved = await result;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw networkError(error, path);
  }

  const { response } = resolved;
  if (response.ok) {
    if (response.status === 204) return undefined as T;
    if (resolved.data !== undefined) return resolved.data as T;
    const body = await readBodySafely(response);
    return (body === null ? undefined : body) as T;
  }

  const body = resolved.error !== undefined ? resolved.error : await readBodySafely(response);
  throw apiErrorFrom(response.status, body, path);
}

/** 原生 fetch 封装 (SSE 之外的一次性流式/文本请求, 例如 Prometheus 指标)。 */
export async function rawRequest(
  method: string,
  path: string,
  init: { query?: Record<string, string | number | boolean | undefined>; signal?: AbortSignal } = {},
): Promise<Response> {
  const url = new URL(apiUrl(path), typeof window === "undefined" ? "http://localhost" : window.location.origin);
  for (const [key, value] of Object.entries(init.query ?? {})) {
    if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }
  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      headers: { Accept: "application/json", ...authHeaders(method) },
      credentials: CROSS_ORIGIN ? "include" : "same-origin",
      signal: init.signal,
    });
  } catch (error) {
    throw networkError(error, path);
  }
  if (!response.ok) {
    const body = await readBodySafely(response);
    const error = apiErrorFrom(response.status, body, path);
    if (response.status === 401) session.signal("unauthorized");
    else if (response.status === 428) session.signal("setup_required");
    throw error;
  }
  return response;
}
