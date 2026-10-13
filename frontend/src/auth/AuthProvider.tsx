import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import * as authApi from "@/api/auth";
import { errorMessage, isApiError } from "@/api/errors";
import { hasSessionCookie, session, type AuthMode, type SessionSnapshot } from "@/api/session";
import type { HealthResponse } from "@/api/types";

/** 前端认证状态机 (F1)。 */
export type AuthStatus =
  /** 启动探测中。 */
  | "probing"
  /** 未认证 → 登录页。 */
  | "anonymous"
  /** 后端首登待设置态 (428 / health.setup_required) → setup 向导。 */
  | "setup_required"
  /** 已认证 → 十域可用。 */
  | "authenticated";

export interface AuthContextValue {
  status: AuthStatus;
  /** 当前凭据轨: cookie (会话 Cookie + CSRF) / bearer (内存 Token) / none。 */
  mode: AuthMode;
  /** 探测阶段的连接错误 (后端未启动等), 登录页需要展示。 */
  connectionError: string | null;
  health: HealthResponse | null;
  /** 登录: 优先换会话 Cookie, 后端未启用时降级 Bearer (凭据只进内存)。 */
  login: (credential: string) => Promise<void>;
  /** 首登设密码并自动登录。 */
  completeSetup: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** 重新探测 (登录页"重试连接")。 */
  reprobe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function subscribeSession(callback: () => void): () => void {
  return session.subscribe(callback);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // getSnapshot 必须带接收者调用: session.get 是原型方法, 裸传引用会在
  // 调用时 this=undefined 直接崩溃 (浏览器冒烟发现的 F1 潜在缺陷)。
  const snapshot: SessionSnapshot = useSyncExternalStore(
    subscribeSession,
    () => session.get(),
    () => session.get(),
  );
  const [status, setStatus] = useState<AuthStatus>("probing");
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const probe = useCallback(async (): Promise<AuthStatus> => {
    // 探测结果直接落到 status (probe 是异步回调, 不在 effect 体内 setState);
    // 仍返回结果供 reprobe 等调用方按需使用。
    const finish = (next: AuthStatus): AuthStatus => {
      setStatus(next);
      return next;
    };

    // 1) /health 免认证: 先拿首登态与子系统概览。
    let healthResult: HealthResponse;
    try {
      healthResult = await authApi.getHealth();
      setHealth(healthResult);
      setConnectionError(null);
      session.setSetupRequired(Boolean(healthResult.setup_required));
    } catch (error) {
      setConnectionError(errorMessage(error));
      setHealth(null);
      // 后端不可达: 不算已认证, 但也不该跳到 setup 向导。
      return finish("anonymous");
    }

    if (healthResult?.setup_required) return finish("setup_required");

    // 2) 认证探针: 200/403 都算已认证 (403 = 已认证但 scope 窄, 由各页面显权限态)。
    try {
      const result = await authApi.probeAuth();
      if (result === "setup_required") return finish("setup_required");
      if (result === "authenticated") {
        // 刷新后凭据来源: 有会话 Cookie = cookie 轨; 否则是内存 Bearer (未刷新过)。
        if (session.get().mode === "none") {
          session.markAuthenticated(hasSessionCookie() ? "cookie" : "bearer");
        }
        return finish("authenticated");
      }
      return finish("anonymous");
    } catch (error) {
      setConnectionError(errorMessage(error));
      return finish("anonymous");
    }
  }, []);

  // 启动探测 (一次)。probe 内部自行落 status; 调度为宏任务并在 cleanup 里取消,
  // effect 本体不触发任何状态更新 (react-hooks/set-state-in-effect)。
  useEffect(() => {
    const timer = window.setTimeout(() => void probe(), 0);
    return () => window.clearTimeout(timer);
  }, [probe]);

  // 全局认证信号: 任意请求 401 → 登录页; 428 → setup 向导。
  useEffect(() => {
    return session.onSignal((signal) => {
      setStatus(signal === "setup_required" ? "setup_required" : "anonymous");
    });
  }, []);

  const login = useCallback(async (credential: string) => {
    const value = credential.trim();
    if (!value) throw new Error("请输入 Token 或管理密码");
    setConnectionError(null);

    // 优先会话 Cookie 轨 (SPEC §8.2 规则 5: 不把裸 Token 长期存在浏览器)。
    const sessionResult = await authApi.createSession(value);
    if (sessionResult) {
      session.markCookieSession();
      setStatus("authenticated");
      return;
    }

    // 后端未启用会话 Cookie (纯 setup 密码部署 / session_auth_enabled=false):
    // 降级 Bearer 轨, 凭据只进内存; 先用探针确认凭据有效再落状态。
    session.markBearerSession(value);
    try {
      const result = await authApi.probeAuth();
      if (result === "setup_required") {
        session.clear({ setupRequired: true });
        setStatus("setup_required");
        throw new Error("控制面处于首登待设置态, 请先设置管理密码");
      }
      if (result !== "authenticated") {
        session.clear();
        setStatus("anonymous");
        throw new Error("Token 或密码无效");
      }
      setStatus("authenticated");
    } catch (error) {
      if (isApiError(error) && error.kind === "unauthorized") {
        session.clear();
        setStatus("anonymous");
        throw new Error("Token 或密码无效", { cause: error });
      }
      session.clear();
      setStatus("anonymous");
      throw error;
    }
  }, []);

  const completeSetup = useCallback(
    async (password: string) => {
      await authApi.completeSetup(password);
      session.setSetupRequired(false);
      // 设完密码后, 该密码即有效 Bearer 凭据 (routes_setup + auth 依赖比对 hash)。
      await login(password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    if (session.get().mode === "cookie") {
      try {
        await authApi.deleteSession();
      } catch {
        // 登出失败不阻塞: Cookie 仍在也只是保持登录, 清本地态后 UI 已退出。
      }
    }
    session.clear({ setupRequired: health?.setup_required ?? false });
    setStatus("anonymous");
  }, [health]);

  const reprobe = useCallback(async () => {
    setStatus("probing");
    await probe(); // probe 内部已落最终 status
  }, [probe]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      mode: snapshot.mode,
      connectionError,
      health,
      login,
      completeSetup,
      logout,
      reprobe,
    }),
    [status, snapshot.mode, connectionError, health, login, completeSetup, logout, reprobe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth 必须在 <AuthProvider> 内使用");
  return context;
}
