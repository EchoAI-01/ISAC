/** 健康 / 首登 setup / 会话认证端点 (F1)。
 *
 * 后端行为要点 (routes_setup.py / routes_auth.py / server.py):
 * - 未配任何静态凭证且未设密码 → admin 端点 428 SETUP_REQUIRED, 仅 /health 与 /setup 可达;
 * - `POST /setup` 设密码后, **密码本身即有效 Bearer 凭据** (auth 依赖比对 PBKDF2 hash);
 * - `POST /auth/session` 仅在配置了 api_token/tokens[] 时挂载 (server.py 只在
 *   `(api_token or parsed_tokens)` 时生成 session_secret); setup 密码部署下返回 404
 *   SESSION_AUTH_DISABLED —— 前端据此降级到 Bearer 轨, 而不是报错。
 */

import { client, unwrap } from "./client";
import type { HealthResponse, SessionLoginResult, SetupCompleteResult, SetupStatus } from "./types";

/** 无需认证: 探针 + 首登态判定 (Dashboard/System 也复用)。 */
export function getHealth(): Promise<HealthResponse> {
  return unwrap<HealthResponse>(client.GET("/health"), "/health");
}

/** 无需认证: 前端首登向导据此决定是否进 setup 流程。 */
export function getSetupStatus(): Promise<SetupStatus> {
  return unwrap<SetupStatus>(client.GET("/api/v1/setup"), "/api/v1/setup");
}

/**
 * 设置首登管理密码。
 *
 * 失败语义: 409 SETUP_ALREADY_DONE (已设置, 轮换走 CLI `isac password reset`);
 * 403 SETUP_NOT_ALLOWED (已配静态凭证, setup 通道关闭);
 * 422 密码短于 MIN_PASSWORD_LENGTH (8 位)。
 */
export function completeSetup(password: string): Promise<SetupCompleteResult> {
  return unwrap<SetupCompleteResult>(
    client.POST("/api/v1/setup", { body: { password } }),
    "/api/v1/setup",
  );
}

/**
 * 用一次性凭据换 HttpOnly 会话 Cookie + CSRF Cookie。
 *
 * 返回 `null` 表示后端未启用会话 Cookie 机制 (404 SESSION_AUTH_DISABLED),
 * 调用方应降级到 Bearer 轨; 其余错误 (401 等) 照常抛出。
 */
export async function createSession(token: string): Promise<SessionLoginResult | null> {
  try {
    return await unwrap<SessionLoginResult>(
      client.POST("/api/v1/auth/session", { body: { token } }),
      "/api/v1/auth/session",
    );
  } catch (error) {
    if (isSessionAuthDisabled(error)) return null;
    throw error;
  }
}

/** 登出: 清除两个 Cookie (DELETE 在 CSRF 中间件里豁免)。 */
export function deleteSession(): Promise<SessionLoginResult> {
  return unwrap<SessionLoginResult>(
    client.DELETE("/api/v1/auth/session"),
    "/api/v1/auth/session",
  );
}

function isSessionAuthDisabled(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { status?: number; code?: string };
  return candidate.status === 404 && (candidate.code === "SESSION_AUTH_DISABLED" || candidate.code === "NOT_FOUND");
}

/**
 * 认证探针: 用一个便宜的已认证端点判断当前凭据是否有效。
 *
 * 返回:
 * - `"authenticated"`  200, 或 403 SCOPE_FORBIDDEN (已认证但 scope 窄, 页面各自显权限态);
 * - `"setup_required"` 428 → 跳首登向导;
 * - `"anonymous"`      401 → 跳登录页;
 * - `"unavailable"`    端点未挂载 (理论上 /agents 恒挂载, 保底分支)。
 */
export type AuthProbe = "authenticated" | "anonymous" | "setup_required" | "unavailable";

export async function probeAuth(): Promise<AuthProbe> {
  const { response } = await client.GET("/api/v1/agents");
  if (response.status === 428) return "setup_required";
  if (response.status === 401) return "anonymous";
  if (response.status === 403) return "authenticated";
  if (response.status === 404) return "unavailable";
  return response.ok ? "authenticated" : "anonymous";
}
