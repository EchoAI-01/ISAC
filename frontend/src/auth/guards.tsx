import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { Spinner } from "@/components/Button";
import { useAuth } from "./AuthProvider";

/** 全屏启动态 (探测认证中; 不闪登录页避免"已登录却看到登录框")。 */
export function SplashScreen({ label = "正在连接控制面…" }: { label?: string }) {
  return (
    <div className="standalone-screen">
      <div className="standalone-card stack" role="status" aria-live="polite">
        <div className="row">
          <Spinner className="spinner--lg" />
          <strong>{label}</strong>
        </div>
        <p className="small muted">
          正在探测 /health 与认证状态。若长时间停留在此页, 说明后端未启动或地址不可达。
        </p>
      </div>
    </div>
  );
}

interface LocationState {
  from?: { pathname?: string; search?: string };
}

function targetAfterAuth(state: unknown): string {
  const from = (state as LocationState | null)?.from;
  if (!from?.pathname) return "/";
  return `${from.pathname}${from.search ?? ""}`;
}

/** 受保护区守卫: 未认证 → /login, 首登态 → /setup。 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "probing") return <SplashScreen />;
  if (status === "setup_required") {
    return <Navigate to="/setup" replace state={{ from: { pathname: location.pathname, search: location.search } }} />;
  }
  if (status !== "authenticated") {
    return <Navigate to="/login" replace state={{ from: { pathname: location.pathname, search: location.search } }} />;
  }
  return <>{children}</>;
}

/** 公开页守卫 (登录 / setup): 已认证时直接回目标页, 避免重复登录。 */
export function RedirectIfAuthenticated({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "authenticated") return <Navigate to={targetAfterAuth(location.state)} replace />;
  return <>{children}</>;
}

/** setup 页专用: 非首登态不让停在向导里 (已设密码 → 登录页)。 */
export function RequireSetup({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "probing") return <SplashScreen />;
  if (status === "authenticated") return <Navigate to={targetAfterAuth(location.state)} replace />;
  if (status !== "setup_required") return <Navigate to="/login" replace />;
  return <>{children}</>;
}
