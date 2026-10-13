import { lazy, Suspense, type ReactNode } from "react";
import { createBrowserRouter, Navigate, type RouteObject } from "react-router-dom";

import { AppShell } from "./AppShell";
import { RedirectIfAuthenticated, RequireAuth, RequireSetup, SplashScreen } from "@/auth/guards";
import { LoginPage } from "@/pages/login/LoginPage";
import { SetupPage } from "@/pages/setup/SetupPage";

// 十域页面按路由分包 (首屏只加载登录/外壳, 进域时才拉对应 chunk)。
const DashboardPage = lazy(() => import("@/pages/dashboard/DashboardPage"));
const AgentsPage = lazy(() => import("@/pages/agents/AgentsPage"));
const AgentDetailPage = lazy(() => import("@/pages/agents/AgentDetailPage"));
const ChannelsRoutingPage = lazy(() => import("@/pages/channels/ChannelsRoutingPage"));
const ProvidersPage = lazy(() => import("@/pages/providers/ProvidersPage"));
const UsagePage = lazy(() => import("@/pages/usage/UsagePage"));
const ExtensionsPage = lazy(() => import("@/pages/extensions/ExtensionsPage"));
const MemoryPage = lazy(() => import("@/pages/memory/MemoryPage"));
const SessionsTasksPage = lazy(() => import("@/pages/sessions/SessionsTasksPage"));
const LogsAuditPage = lazy(() => import("@/pages/logs/LogsAuditPage"));
const SystemPage = lazy(() => import("@/pages/system/SystemPage"));

function lazyPage(node: ReactNode): ReactNode {
  return <Suspense fallback={<SplashScreen label="加载页面…" />}>{node}</Suspense>;
}

function NotFoundPage() {
  return (
    <div className="stack">
      <h1 className="page-header__title">页面不存在</h1>
      <p className="muted">该路径不属于十域中的任何一页。</p>
      <div>
        <a className="btn btn--secondary" href="/">
          回到 Dashboard
        </a>
      </div>
    </div>
  );
}

const shellRoutes: RouteObject[] = [
  { index: true, element: lazyPage(<DashboardPage />) },
  { path: "agents", element: lazyPage(<AgentsPage />) },
  { path: "agents/:agentId", element: lazyPage(<AgentDetailPage />) },
  { path: "channels", element: lazyPage(<ChannelsRoutingPage />) },
  { path: "providers", element: lazyPage(<ProvidersPage />) },
  { path: "usage", element: lazyPage(<UsagePage />) },
  { path: "extensions", element: lazyPage(<ExtensionsPage />) },
  { path: "memory", element: lazyPage(<MemoryPage />) },
  { path: "sessions", element: lazyPage(<SessionsTasksPage />) },
  { path: "logs", element: lazyPage(<LogsAuditPage />) },
  { path: "system", element: lazyPage(<SystemPage />) },
  { path: "*", element: <NotFoundPage /> },
];

export const router = createBrowserRouter([
  {
    path: "/login",
    element: (
      <RedirectIfAuthenticated>
        <LoginPage />
      </RedirectIfAuthenticated>
    ),
  },
  {
    path: "/setup",
    element: (
      <RequireSetup>
        <SetupPage />
      </RequireSetup>
    ),
  },
  {
    path: "/",
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: shellRoutes,
  },
  { path: "*", element: <Navigate to="/" replace /> },
]);
