import type { ReactNode } from "react";

import { isApiError, type ApiErrorKind } from "@/api/errors";
import { cn } from "@/lib/cn";
import { Button } from "./Button";

/**
 * 统一状态视图 (CONTROL_PLANE_SPEC §8.5: 所有页面具备
 * loading / empty / error / stale / permission-denied 状态)。
 *
 * 五态各自有独立文案与可访问语义, 不共用一个"暂无数据":
 * - permission-denied 要说清缺哪个 scope, 否则用户会以为系统没数据;
 * - unavailable 要指向启用该子系统的配置项 (api.md "条件挂载");
 * - error 要给出错误码与重试入口。
 */

export interface StateViewProps {
  variant: "loading" | "empty" | "error" | "denied" | "unavailable" | "stale";
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: string;
  className?: string;
}

const ICONS: Record<StateViewProps["variant"], string> = {
  loading: "⏳",
  empty: "▫",
  error: "⚠",
  denied: "🔒",
  unavailable: "○",
  stale: "↻",
};

export function StateView({ variant, title, description, actions, icon, className }: StateViewProps) {
  const isAlert = variant === "error" || variant === "denied";
  return (
    <div
      className={cn("state", variant === "error" && "state--error", variant === "denied" && "state--denied", className)}
      role={isAlert ? "alert" : variant === "loading" ? "status" : undefined}
      aria-busy={variant === "loading" || undefined}
      data-state={variant}
    >
      <span className="state__icon" aria-hidden="true">
        {icon ?? ICONS[variant]}
      </span>
      <div className="state__title">{title}</div>
      {description ? <div>{description}</div> : null}
      {actions ? <div className="state__actions">{actions}</div> : null}
    </div>
  );
}

export function LoadingState({ label = "加载中…" }: { label?: string }) {
  return (
    <StateView
      variant="loading"
      title={label}
      icon=" "
      description={<span className="spinner spinner--lg" aria-hidden="true" />}
    />
  );
}

export function EmptyState({
  title = "暂无数据",
  description,
  actions,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return <StateView variant="empty" title={title} description={description} actions={actions} />;
}

export function ErrorState({
  title = "加载失败",
  description,
  onRetry,
  retrying,
}: {
  title?: ReactNode;
  description?: ReactNode;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  return (
    <StateView
      variant="error"
      title={title}
      description={description}
      actions={onRetry ? <Button variant="secondary" onClick={onRetry} loading={retrying}>重试</Button> : undefined}
    />
  );
}

/** scope 不足 (403 SCOPE_FORBIDDEN / CSRF_REQUIRED / TENANT_FORBIDDEN)。 */
export function PermissionDeniedState({
  scope,
  message,
  title = "权限不足",
}: {
  scope?: string;
  message?: string;
  title?: ReactNode;
}) {
  return (
    <StateView
      variant="denied"
      title={title}
      description={
        <>
          <div>{message ?? "当前凭据的 scope 不覆盖该数据面。"}</div>
          {scope ? (
            <div className="small">
              需要 scope: <code className="code-inline">{scope}</code> (或 <code className="code-inline">*</code> 通配)
            </div>
          ) : null}
          <div className="small muted">在 config.jsonc 的 control.tokens[] 里为该 token 补 scope 后重新登录。</div>
        </>
      }
    />
  );
}

/** 可选子系统未启用 (路由未挂载 → 404 无业务 code / 405)。 */
export function UnavailableState({
  title = "该子系统未启用",
  description,
  configHint,
}: {
  title?: ReactNode;
  description?: ReactNode;
  configHint?: string;
}) {
  return (
    <StateView
      variant="unavailable"
      title={title}
      description={
        <>
          <div>{description ?? "对应端点未挂载 (后端按子系统启用状态条件挂载路由)。"}</div>
          {configHint ? (
            <div className="small">
              启用方式: <code className="code-inline">{configHint}</code>
            </div>
          ) : null}
        </>
      }
    />
  );
}

/** 端点 → 启用配置提示 (api.md "条件挂载" 一节的口径)。 */
export const UNAVAILABLE_HINTS: Record<string, string> = {
  "/api/v1/usage": "observability.usage.enabled = true",
  "/api/v1/subagent-runs": "subagent.enabled = true",
  "/api/v1/memory": "memory.enabled = true",
  "/api/v1/sessions": "memory.enabled = true (会话消息来自 episodes)",
  "/api/v1/providers": "配置 llm / multimodal_providers (ProviderManager + ModelCatalog)",
  "/api/v1/artifacts": "配置 artifacts 存储 (ArtifactStore)",
  "/api/v1/workflows": "control.workflow.enabled = true",
  "/api/v1/identity": "identity.enabled = true",
  "/api/v1/webhooks": "webhooks.enabled = true",
  "/api/v1/automation": "webhooks.enabled = true",
  "/api/v1/tenants": "tenancy.enabled = true",
  "/api/v1/approvals": "tools.approval 审批门已接线 (ApprovalGate)",
  "/api/v1/logs/tail": "logging 缓冲已启用 (LogBuffer)",
  "/api/v1/plugins/install": "control.plugins.allow_install = true",
  "/api/v1/config/global": "控制面注入了 global_config (生产恒注入)",
};

/** 按请求路径找最匹配的启用提示。 */
export function unavailableHint(path?: string): string | undefined {
  if (!path) return undefined;
  const match = Object.keys(UNAVAILABLE_HINTS)
    .filter((prefix) => path.startsWith(prefix))
    .sort((a, b) => b.length - a.length)[0];
  return match ? UNAVAILABLE_HINTS[match] : undefined;
}

/** scope 提示: 端点 → 所需 scope (与后端 scope_dependency 接线一致)。 */
export const SCOPE_HINTS: Record<string, string> = {
  "/api/v1/agents": "agent:read / agent:write",
  "/api/v1/routing": "routing:write",
  "/api/v1/links": "link:write",
  "/api/v1/plugins": "plugin:read / plugin:write",
  "/api/v1/providers": "provider:read / provider:write",
  "/api/v1/artifacts": "artifact:read / artifact:delete",
  "/api/v1/usage": "usage:read (明细需 usage:detail)",
  "/api/v1/sessions": "memory:read",
  "/api/v1/memory": "memory:read / memory:write",
  "/api/v1/subagent-runs": "subagent:read / subagent:run / subagent:cancel / subagent:log:read",
  "/api/v1/approvals": "tools:read / tools:write",
  "/api/v1/config": "config:read / config:write",
  "/api/v1/audit": "* (通配)",
  "/api/v1/logs/tail": "* (通配)",
  "/api/v1/webhooks": "webhook:read / webhook:write",
  "/api/v1/automation": "webhook:write",
  "/api/v1/tenants": "tenant:read / tenant:write",
  "/api/v1/identity": "identity:read / identity:write",
  "/api/v1/workflows": "workflow:read / workflow:write",
};

export function scopeHint(path?: string): string | undefined {
  if (!path) return undefined;
  const match = Object.keys(SCOPE_HINTS)
    .filter((prefix) => path.startsWith(prefix))
    .sort((a, b) => b.length - a.length)[0];
  return match ? SCOPE_HINTS[match] : undefined;
}

/** 按错误种类渲染对应状态视图 (页面统一入口)。 */
export function ErrorBoundaryState({
  error,
  onRetry,
  retrying,
}: {
  error: unknown;
  onRetry?: () => void;
  retrying?: boolean;
}) {
  if (!isApiError(error)) {
    return (
      <ErrorState
        title="请求失败"
        description={error instanceof Error ? error.message : String(error)}
        onRetry={onRetry}
        retrying={retrying}
      />
    );
  }

  const kind: ApiErrorKind = error.kind;
  if (kind === "forbidden") {
    return <PermissionDeniedState scope={scopeHint(error.path)} message={error.message} />;
  }
  if (kind === "unavailable") {
    return (
      <UnavailableState
        description={error.message}
        configHint={unavailableHint(error.path)}
      />
    );
  }
  if (kind === "network") {
    return (
      <ErrorState
        title="无法连接控制面"
        description={
          <>
            <div>{error.message}</div>
            <div className="small">确认后端已启动 (默认 127.0.0.1:8765), 或检查 Vite 代理 / CORS 配置。</div>
          </>
        }
        onRetry={onRetry}
        retrying={retrying}
      />
    );
  }
  return (
    <ErrorState
      title={`请求失败 (${error.code})`}
      description={
        <>
          <div>{error.message}</div>
          <div className="small muted">
            HTTP {error.status} · <code className="code-inline">{error.path}</code>
          </div>
        </>
      }
      onRetry={onRetry}
      retrying={retrying}
    />
  );
}
