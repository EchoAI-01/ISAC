/** Webhook / 租户 / 身份归一 / 工作流端点。
 *
 * 这四组都是条件挂载 (对应子系统未启用即 404 → unavailable):
 * webhooks 需 WebhookManager, tenants 需 TenantManager, identity 需
 * identity.enabled=true, workflows 需 control.workflow.enabled=true。
 */

import { client, unwrap } from "./client";
import type {
  IdentityConflict,
  StatusResult,
  TenantDto,
  WebhookSubscriptions,
  WebhookTriggerResult,
  WorkflowDto,
} from "./types";

// ── Webhook (R2-③) ─────────────────────────────

/** 订阅清单: event → url 列表 (URL 可能内嵌凭据, 展示需脱敏)。 */
export function listWebhooks(event?: string): Promise<WebhookSubscriptions> {
  return unwrap<WebhookSubscriptions>(
    client.GET("/api/v1/webhooks", { params: { query: { event } } }),
    "/api/v1/webhooks",
  );
}

export function subscribeWebhook(event: string, url: string): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.POST("/api/v1/webhooks", { body: { event, url } }),
    "/api/v1/webhooks",
  );
}

export function unsubscribeWebhook(event: string, url: string): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.DELETE("/api/v1/webhooks", { params: { query: { event, url } } }),
    "/api/v1/webhooks",
  );
}

/** 手动触发一次事件推送 (返回每个订阅者的投递结果)。 */
export function triggerAutomation(
  event: string,
  data: Record<string, unknown> = {},
): Promise<WebhookTriggerResult> {
  return unwrap<WebhookTriggerResult>(
    client.POST("/api/v1/automation/trigger", { body: { event, data } }),
    "/api/v1/automation/trigger",
  );
}

/** Webhook 事件目录 (CONTROL_PLANE_SPEC §5.1; 当前仅两个已接线, 见 spec 注)。 */
export const WEBHOOK_EVENT_CATALOG = [
  "message.received",
  "message.routed",
  "message.responded",
  "message.sent",
  "agent.created",
  "agent.started",
  "agent.stopped",
  "inter_agent.sent",
  "plugin.loaded",
  "plugin.failed",
  "memory.created",
  "model.usage_recorded",
  "provider.health_changed",
  "control.audit",
] as const;

/** 已接线 (有生产者) 的事件; 其余为目录预留, UI 必须标注避免用户误判。 */
export const WEBHOOK_EVENTS_WIRED = new Set(["message.responded", "message.sent"]);

// ── 租户 (#25/U4) ──────────────────────────────

/** 绑定租户的 token 只能看到自己的租户 (后端强制, 前端不做二次过滤)。 */
export function listTenants(organization?: string): Promise<TenantDto[]> {
  return unwrap<TenantDto[]>(
    client.GET("/api/v1/tenants", { params: { query: { organization } } }),
    "/api/v1/tenants",
  );
}

export function getTenant(tenantId: string): Promise<TenantDto> {
  return unwrap<TenantDto>(
    client.GET("/api/v1/tenants/{tenant_id}", { params: { path: { tenant_id: tenantId } } }),
    `/api/v1/tenants/${tenantId}`,
  );
}

/** 创建租户: 绑定租户的 token 恒 403 TENANT_FORBIDDEN。 */
export function createTenant(payload: {
  tenant_id?: string;
  organization_id?: string;
  display_name?: string;
}): Promise<TenantDto> {
  return unwrap<TenantDto>(client.POST("/api/v1/tenants", { body: payload }), "/api/v1/tenants");
}

/** 删除租户 (级联清理数据面打标行, best-effort) —— 高影响, 必须二次确认。 */
export function deleteTenant(tenantId: string): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.DELETE("/api/v1/tenants/{tenant_id}", { params: { path: { tenant_id: tenantId } } }),
    `/api/v1/tenants/${tenantId}`,
  );
}

export function addTenantMember(
  tenantId: string,
  memberId: string,
  memberType = "user",
): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.POST("/api/v1/tenants/{tenant_id}/members", {
      params: { path: { tenant_id: tenantId } },
      body: { member_id: memberId, member_type: memberType },
    }),
    `/api/v1/tenants/${tenantId}/members`,
  );
}

export function removeTenantMember(
  tenantId: string,
  memberId: string,
  memberType = "user",
): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.DELETE("/api/v1/tenants/{tenant_id}/members/{member_id}", {
      params: { path: { tenant_id: tenantId, member_id: memberId }, query: { member_type: memberType } },
    }),
    `/api/v1/tenants/${tenantId}/members/${memberId}`,
  );
}

// ── 身份归一 (S4) ──────────────────────────────

export function bindIdentity(payload: {
  person_id: string;
  platform: string;
  platform_user_id: string;
  display_name?: string;
  connection_id?: string;
}): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.POST("/api/v1/identity/bind", {
      body: {
        person_id: payload.person_id,
        platform: payload.platform,
        platform_user_id: payload.platform_user_id,
        display_name: payload.display_name ?? "",
        connection_id: payload.connection_id ?? "",
      },
    }),
    "/api/v1/identity/bind",
  );
}

/** 未裁决的低置信度冲突 (candidates 是 JSON 字符串, 需前端解析后呈现)。 */
export function listIdentityConflicts(): Promise<IdentityConflict[]> {
  return unwrap<IdentityConflict[]>(
    client.GET("/api/v1/identity/conflicts"),
    "/api/v1/identity/conflicts",
  );
}

export function resolveIdentityConflict(
  conflictId: string,
  personId: string,
): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.POST("/api/v1/identity/conflicts/{conflict_id}/resolve", {
      params: { path: { conflict_id: conflictId } },
      body: { person_id: personId },
    }),
    `/api/v1/identity/conflicts/${conflictId}/resolve`,
  );
}

// ── 工作流 (O3) ────────────────────────────────

export function listWorkflows(): Promise<WorkflowDto[]> {
  return unwrap<WorkflowDto[]>(client.GET("/api/v1/workflows"), "/api/v1/workflows");
}

export function getWorkflow(workflowId: string): Promise<WorkflowDto> {
  return unwrap<WorkflowDto>(
    client.GET("/api/v1/workflows/{workflow_id}", {
      params: { path: { workflow_id: workflowId } },
    }),
    `/api/v1/workflows/${workflowId}`,
  );
}

export function startWorkflow(workflowId: string): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.POST("/api/v1/workflows/{workflow_id}/start", {
      params: { path: { workflow_id: workflowId } },
    }),
    `/api/v1/workflows/${workflowId}/start`,
  );
}
