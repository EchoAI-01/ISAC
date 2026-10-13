import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthProvider";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { NAV_ITEMS, navItemForPath, shortcutLabel } from "./nav";

/** 十域应用外壳: 侧栏 + 顶栏 + 内容区 (移动端侧栏转抽屉)。 */
export function AppShell() {
  const { health, logout, mode } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const current = navItemForPath(location.pathname);

  // 路由变化即关闭移动抽屉 (避免遮挡内容)。用 React 官方"渲染期对照前值调整
  // state"模式替代 effect 里 setState (react-hooks/set-state-in-effect)。
  const routeKey = `${location.pathname}${location.search}`;
  const [lastRoute, setLastRoute] = useState(routeKey);
  if (routeKey !== lastRoute) {
    setLastRoute(routeKey);
    setSidebarOpen(false);
  }

  // 键盘快捷键 Alt+1..Alt+9 / Alt+0 直达十域 (WCAG 2.1.1 键盘可达)。
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.ctrlKey || event.metaKey) return;
      const digit = Number(event.key);
      if (!Number.isFinite(digit)) return;
      const target = NAV_ITEMS.find((item) => item.index % 10 === digit);
      if (!target) return;
      event.preventDefault();
      navigate(target.to);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate]);

  const healthTone = health?.status === "ok" ? "success" : health ? "warning" : "neutral";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主内容
      </a>

      {sidebarOpen ? (
        <div
          className="sidebar-scrim"
          onClick={() => setSidebarOpen(false)}
          role="presentation"
          aria-hidden="true"
        />
      ) : null}

      <aside className="app-sidebar" data-open={sidebarOpen} aria-label="主导航">
        <div className="app-sidebar__brand">
          <span aria-hidden="true">◈</span>
          <span>ISAC 控制台</span>
        </div>
        <nav className="app-sidebar__nav" aria-label="十个管理域">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className="nav-link" title={item.description}>
              <span className="nav-link__index" aria-hidden="true">
                {item.index % 10}
              </span>
              <span className="grow">{item.label}</span>
              <span className="sr-only">({shortcutLabel(item.index)})</span>
            </NavLink>
          ))}
        </nav>
        <div className="app-sidebar__footer">
          <div className="row row--tight">
            <Badge tone={healthTone} dot>
              {health ? `后端 ${health.status}` : "后端状态未知"}
            </Badge>
          </div>
          <div className="xs" style={{ marginTop: "var(--space-2)" }}>
            凭据轨: {mode === "cookie" ? "会话 Cookie" : mode === "bearer" ? "Bearer (内存)" : "未登录"}
          </div>
        </div>
      </aside>

      <header className="app-header">
        <Button
          variant="ghost"
          size="sm"
          className="sidebar-toggle"
          onClick={() => setSidebarOpen((open) => !open)}
          aria-expanded={sidebarOpen}
          aria-controls="mobile-sidebar"
          accessibleName={sidebarOpen ? "关闭导航" : "打开导航"}
        >
          ☰
        </Button>
        <div className="app-header__title">
          {current.label}
          <span className="sr-only"> — {current.description}</span>
        </div>
        <div className="row row--tight">
          {health?.setup_required ? <Badge tone="warning">首登待设置</Badge> : null}
          {health?.subsystems?.llm === "stub" ? (
            <Badge tone="warning" title="未配置真实 LLM key, 当前为 Stub Provider">
              LLM stub
            </Badge>
          ) : null}
          <Button variant="secondary" size="sm" onClick={() => void logout()}>
            登出
          </Button>
        </div>
      </header>

      <main className="app-main" id="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
