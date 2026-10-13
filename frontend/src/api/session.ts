/** 认证会话状态 (框架无关的单例存储)。
 *
 * 为什么不用 React Context 直接持有: API 客户端中间件 (openapi-fetch onRequest)
 * 与 SSE 客户端都在 React 渲染树之外发起请求, 需要读当前凭据模式; 全局 401/428
 * 也需要把信号广播给路由守卫。这里做最小 store, React 侧用 `useSession()` 订阅。
 *
 * 安全约束 (CONTROL_PLANE_SPEC §8.2 规则 4): 管理 Token / 密码 **只存内存**,
 * 绝不写 localStorage/sessionStorage/Cookie。刷新页面后:
 * - cookie 模式: HttpOnly 会话 Cookie 仍在, 自动恢复;
 * - bearer 模式 (后端未启用会话 Cookie, 如纯 setup 密码部署): 需重新登录。
 */

export type AuthMode =
  /** 尚未确定 (启动探测中) 或未登录。 */
  | "none"
  /** POST /auth/session 成功, 靠 HttpOnly 会话 Cookie + CSRF 双提交认证。 */
  | "cookie"
  /** 降级轨: Authorization: Bearer <token> (后端返回 404 SESSION_AUTH_DISABLED 时)。 */
  | "bearer";

export type AuthSignal = "unauthorized" | "setup_required";

export interface SessionSnapshot {
  mode: AuthMode;
  /** bearer 模式下的凭据 (内存态, 永不出现在持久化存储与日志中)。 */
  token: string | null;
  /** 是否已通过一次成功探测/登录 (UI 据此决定是否渲染受保护区)。 */
  authenticated: boolean;
  /** 后端 /health 或 /setup 报告的首登待设置态。 */
  setupRequired: boolean;
}

type Listener = (snapshot: SessionSnapshot) => void;
type SignalListener = (signal: AuthSignal) => void;

const INITIAL: SessionSnapshot = {
  mode: "none",
  token: null,
  authenticated: false,
  setupRequired: false,
};

class SessionStore {
  private snapshot: SessionSnapshot = { ...INITIAL };
  private readonly listeners = new Set<Listener>();
  private readonly signalListeners = new Set<SignalListener>();

  get(): SessionSnapshot {
    return this.snapshot;
  }

  /** 当前 Bearer 凭据 (无则 null)。 */
  get bearerToken(): string | null {
    return this.snapshot.mode === "bearer" ? this.snapshot.token : null;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** 订阅全局认证信号 (401 → 登录页, 428 → setup 向导)。 */
  onSignal(listener: SignalListener): () => void {
    this.signalListeners.add(listener);
    return () => {
      this.signalListeners.delete(listener);
    };
  }

  private emit(): void {
    const snapshot = this.snapshot;
    for (const listener of this.listeners) listener(snapshot);
  }

  private update(patch: Partial<SessionSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    this.emit();
  }

  /** 登录成功 (会话 Cookie 轨)。 */
  markCookieSession(): void {
    this.update({ mode: "cookie", token: null, authenticated: true });
  }

  /** 登录成功 (Bearer 降级轨)。凭据只进内存。 */
  markBearerSession(token: string): void {
    this.update({ mode: "bearer", token, authenticated: true });
  }

  /** 探测到已认证 (例如刷新页面后 Cookie 仍有效)。 */
  markAuthenticated(mode: AuthMode = "cookie"): void {
    if (this.snapshot.authenticated && this.snapshot.mode === mode) return;
    this.update({ mode, authenticated: true });
  }

  setSetupRequired(required: boolean): void {
    if (this.snapshot.setupRequired === required) return;
    this.update({ setupRequired: required });
  }

  /** 登出 / 凭据失效。 */
  clear(opts: { setupRequired?: boolean } = {}): void {
    this.snapshot = { ...INITIAL, setupRequired: opts.setupRequired ?? false };
    this.emit();
  }

  /** 由 API 客户端在 401/428 时调用。 */
  signal(kind: AuthSignal): void {
    if (kind === "unauthorized") {
      // 凭据失效: 清认证态, 但保留 setup 标志由路由守卫重新探测。
      if (this.snapshot.authenticated || this.snapshot.mode !== "none") {
        this.snapshot = { ...this.snapshot, mode: "none", token: null, authenticated: false };
        this.emit();
      }
    } else {
      this.setSetupRequired(true);
    }
    for (const listener of this.signalListeners) listener(kind);
  }
}

export const session = new SessionStore();

const CSRF_COOKIE_NAME = "csrf_token";
const SESSION_COOKIE_NAME = "isac_session";

/** 读取非 HttpOnly 的 CSRF Cookie (双提交校验回填 X-CSRF-Token 用)。 */
export function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]!) : null;
}

/** 会话 Cookie 是否存在 (HttpOnly 读不到值, 但名字可见) —— 用于刷新后快速判断。 */
export function hasSessionCookie(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.includes(`${SESSION_COOKIE_NAME}=`);
}

export { CSRF_COOKIE_NAME, SESSION_COOKIE_NAME };
