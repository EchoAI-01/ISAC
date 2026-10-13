/** Agent 管理端点 (routes_agents.py)。
 *
 * 创建路径强制套用受限默认模板 (CR3-L1): payload 里的能力字段
 * (tools_policy / plugins_allow / plugins_deny / commands_allow / mcp_servers)
 * 会被后端丢弃, 需要放宽必须创建后 PATCH 显式授予 —— UI 必须把这条讲清楚,
 * 否则用户会以为创建时填的能力生效了。
 */

import { client, unwrap } from "./client";
import type { AgentConfig, AgentPatchResult, AgentSummary, PluginMatrix, StatusResult } from "./types";

export function listAgents(): Promise<AgentSummary[]> {
  return unwrap<AgentSummary[]>(client.GET("/api/v1/agents"), "/api/v1/agents");
}

export function getAgent(agentId: string): Promise<AgentSummary> {
  return unwrap<AgentSummary>(
    client.GET("/api/v1/agents/{agent_id}", { params: { path: { agent_id: agentId } } }),
    `/api/v1/agents/${agentId}`,
  );
}

/** 创建 Agent (能力字段被后端剥离, 见模块注释)。 */
export function createAgent(payload: {
  agent_id: string;
  display_name?: string;
  trigger_words?: string[];
  memory_namespace?: string;
  persona?: Record<string, unknown>;
  [key: string]: unknown;
}): Promise<AgentSummary> {
  return unwrap<AgentSummary>(
    client.POST("/api/v1/agents", { body: payload }),
    "/api/v1/agents",
  );
}

export function startAgent(agentId: string): Promise<AgentSummary> {
  return unwrap<AgentSummary>(
    client.POST("/api/v1/agents/{agent_id}/start", { params: { path: { agent_id: agentId } } }),
    `/api/v1/agents/${agentId}/start`,
  );
}

export function stopAgent(agentId: string): Promise<AgentSummary> {
  return unwrap<AgentSummary>(
    client.POST("/api/v1/agents/{agent_id}/stop", { params: { path: { agent_id: agentId } } }),
    `/api/v1/agents/${agentId}/stop`,
  );
}

/**
 * 销毁 Agent。keep_memory=false 会清理该 Agent 命名空间下的记忆
 * (shared 命名空间被后端拒绝清理) —— 属高影响操作, UI 必须二次确认。
 */
export function destroyAgent(agentId: string, keepMemory = true): Promise<AgentSummary> {
  return unwrap<AgentSummary>(
    client.DELETE("/api/v1/agents/{agent_id}", {
      params: { path: { agent_id: agentId }, query: { keep_memory: keepMemory } },
    }),
    `/api/v1/agents/${agentId}`,
  );
}

/** 读取全量配置 + 真实 revision (敏感键为脱敏哨兵 `__ISAC_REDACTED__`)。 */
export function getAgentConfig(agentId: string): Promise<AgentConfig> {
  return unwrap<AgentConfig>(
    client.GET("/api/v1/agents/{agent_id}/config", { params: { path: { agent_id: agentId } } }),
    `/api/v1/agents/${agentId}/config`,
  );
}

/**
 * 部分更新配置 (If-Match 乐观锁, Header 优先)。
 *
 * revision 不符 → 409 CONFIG_CONFLICT (含 current_revision), 调用方必须展示
 * 服务器版本与本地变更, 不静默覆盖 (SPEC §8.2 规则 3)。
 */
export function patchAgent(
  agentId: string,
  payload: Partial<AgentConfig>,
  ifMatch?: number,
): Promise<AgentPatchResult> {
  return unwrap<AgentPatchResult>(
    client.PATCH("/api/v1/agents/{agent_id}", {
      params: { path: { agent_id: agentId } },
      body: payload,
      ...(ifMatch === undefined ? {} : { headers: { "If-Match": String(ifMatch) } }),
    }),
    `/api/v1/agents/${agentId}`,
  );
}

/** 插件启用矩阵 (Agent 级)。 */
export function getPluginMatrix(agentId: string): Promise<PluginMatrix> {
  return unwrap<PluginMatrix>(
    client.GET("/api/v1/agents/{agent_id}/plugins", { params: { path: { agent_id: agentId } } }),
    `/api/v1/agents/${agentId}/plugins`,
  );
}

export function putPluginMatrix(agentId: string, matrix: PluginMatrix): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.PUT("/api/v1/agents/{agent_id}/plugins", {
      params: { path: { agent_id: agentId } },
      // 契约里请求体是宽松 dict, 这里显式转 Record 保持类型安全边界在一处。
      body: { plugins_allow: matrix.plugins_allow, plugins_deny: matrix.plugins_deny },
    }),
    `/api/v1/agents/${agentId}/plugins`,
  );
}

/** GET 回显的脱敏哨兵 (routes_agents.REDACTED_SENTINEL)。 */
export const REDACTED_SENTINEL = "__ISAC_REDACTED__";

/** 判断某个值是否为脱敏哨兵 (敏感字段 UI 显示"已配置", 永不回显明文)。 */
export function isRedacted(value: unknown): boolean {
  return value === REDACTED_SENTINEL;
}
