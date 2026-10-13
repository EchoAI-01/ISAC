/** 路由规则与互联 Link 端点 (routes_routing.py)。
 *
 * 注意: CONTROL_PLANE_SPEC §3.3 的 `/channels*` REST 端点**后端未实现**
 * (绑定能力仅 MCP 工具提供), 因此 Channel 状态只能从 `/health` 聚合读取;
 * Channels & Routing 页必须把这条限制显式告知用户, 不假装可绑定。
 */

import { client, unwrap } from "./client";
import type { InterAgentLink, RoutingRules, StatusResult } from "./types";

export function getRoutingRules(): Promise<RoutingRules> {
  return unwrap<RoutingRules>(client.GET("/api/v1/routing/rules"), "/api/v1/routing/rules");
}

/** 覆盖式更新 (整体 PUT, 后端不做部分合并)。 */
export function putRoutingRules(rules: RoutingRules): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.PUT("/api/v1/routing/rules", {
      body: { bindings: rules.bindings, default_agents: rules.default_agents },
    }),
    "/api/v1/routing/rules",
  );
}

export function listLinks(): Promise<InterAgentLink[]> {
  return unwrap<InterAgentLink[]>(client.GET("/api/v1/links"), "/api/v1/links");
}

/**
 * 创建 Link。permissions 默认空 = notify/handoff/memory_query 全部拒绝
 * (deny-by-default), 只有 ask 不经 permissions 门 —— UI 要把这层语义讲清楚。
 */
export function addLink(link: {
  from_agent: string;
  to_agent: string;
  direction?: "both" | "oneway";
  enabled?: boolean;
  permissions?: string[];
  visible_memory_scopes?: string[];
  max_context_messages?: number;
}): Promise<StatusResult> {
  return unwrap<StatusResult>(client.POST("/api/v1/links", { body: link }), "/api/v1/links");
}

/** 删除 Link (DELETE 用 query 参数, 不是路径参数)。 */
export function removeLink(fromAgent: string, toAgent: string): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.DELETE("/api/v1/links", {
      params: { query: { from_agent: fromAgent, to_agent: toAgent } },
    }),
    "/api/v1/links",
  );
}
