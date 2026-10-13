/** 读查询 hooks (TanStack Query)。
 *
 * 全局默认 (见 app/providers.tsx 的 QueryClient) 已覆盖: 只重试网络/5xx/限流、
 * staleTime 10s、窗口重聚焦刷新。这里只写**每个域需要覆盖**的选项:
 * - `enabled`: 依赖路径参数的查询在参数缺失时不发请求;
 * - `staleTime`: 契约/Schema 类基本不变, 拉长到 5min;
 * - `refetchInterval`: 健康与待审批需要准实时。
 *
 * 4xx 里的 permission-denied / unavailable 一律不吞: 页面用 <QueryState> 渲染对应
 * 状态 (吞掉就无法区分"空数据"与"没权限", 这是 v1 内置 WebUI 的老问题)。
 */

import { useQuery } from "@tanstack/react-query";

import * as agentsApi from "@/api/agents";
import * as authApi from "@/api/auth";
import * as configApi from "@/api/config";
import * as governanceApi from "@/api/governance";
import * as memoryApi from "@/api/memory";
import * as pluginsApi from "@/api/plugins";
import * as providersApi from "@/api/providers";
import * as routingApi from "@/api/routing";
import * as sessionsApi from "@/api/sessions";
import * as subagentApi from "@/api/subagent";
import * as systemApi from "@/api/system";
import * as usageApi from "@/api/usage";
import { isApiError } from "@/api/errors";
import { queryKeys } from "./queryKeys";

/** 只对可恢复错误重试 (网络 / 5xx / 429); 4xx 是确定性结果。 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  if (!isApiError(error)) return true;
  return error.kind === "network" || error.kind === "server" || error.kind === "rate_limited";
}

const STATIC_STALE = 300_000;

// ── 系统 / 健康 ────────────────────────────────

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: authApi.getHealth,
    staleTime: 5_000,
    refetchInterval: 15_000,
  });
}

export function useSetupStatus(enabled = true) {
  return useQuery({
    queryKey: queryKeys.setupStatus,
    queryFn: authApi.getSetupStatus,
    staleTime: STATIC_STALE,
    refetchOnWindowFocus: false,
    enabled,
  });
}

export function useMetricsSnapshot() {
  return useQuery({ queryKey: queryKeys.metrics, queryFn: systemApi.getMetricsSnapshot });
}

export function useAudit(query: systemApi.AuditQuery) {
  return useQuery({
    queryKey: queryKeys.audit(query),
    queryFn: () => systemApi.queryAudit(query),
  });
}

// ── Agent ──────────────────────────────────────

export function useAgents() {
  return useQuery({ queryKey: queryKeys.agents.list(), queryFn: agentsApi.listAgents });
}

export function useAgentConfig(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.agents.config(agentId ?? ""),
    queryFn: () => agentsApi.getAgentConfig(agentId as string),
    enabled: Boolean(agentId),
  });
}

export function usePluginMatrix(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.agents.pluginMatrix(agentId ?? ""),
    queryFn: () => agentsApi.getPluginMatrix(agentId as string),
    enabled: Boolean(agentId),
  });
}

// ── 路由 / Link ────────────────────────────────

export function useRoutingRules() {
  return useQuery({ queryKey: queryKeys.routing.rules(), queryFn: routingApi.getRoutingRules });
}

export function useLinks() {
  return useQuery({ queryKey: queryKeys.routing.links(), queryFn: routingApi.listLinks });
}

// ── 插件 (F4) ──────────────────────────────────

export function useLoadedPlugins() {
  return useQuery({ queryKey: queryKeys.plugins.loaded(), queryFn: pluginsApi.listLoadedPlugins });
}

export function useMarketplace(refresh = false) {
  return useQuery({
    queryKey: queryKeys.plugins.marketplace(refresh),
    queryFn: () => pluginsApi.listMarketplace(refresh),
    staleTime: 60_000,
  });
}

export function useFailedPlugins() {
  return useQuery({ queryKey: queryKeys.plugins.failed(), queryFn: pluginsApi.listFailedPlugins });
}

// ── Provider / 模型 / 制品 ─────────────────────

export function useProviders() {
  return useQuery({ queryKey: queryKeys.providers.list(), queryFn: providersApi.listProviders });
}

export function useModels() {
  return useQuery({
    queryKey: queryKeys.providers.models(),
    queryFn: providersApi.listModels,
    staleTime: 60_000,
  });
}

export function useArtifacts() {
  return useQuery({ queryKey: queryKeys.artifacts.list(), queryFn: providersApi.listArtifacts });
}

// ── 用量与成本 ─────────────────────────────────

export function useUsageSummary(query: usageApi.UsageSummaryQuery) {
  return useQuery({
    queryKey: queryKeys.usage.summary(query),
    queryFn: () => usageApi.getUsageSummary(query),
  });
}

export function useUsageEvents(query: usageApi.UsageFilter & { limit?: number; offset?: number }) {
  return useQuery({
    queryKey: queryKeys.usage.events(query),
    queryFn: () => usageApi.getUsageEvents(query),
  });
}

export function useUsageTimeseries(query: usageApi.UsageTimeseriesQuery) {
  return useQuery({
    queryKey: queryKeys.usage.timeseries(query),
    queryFn: () => usageApi.getUsageTimeseries(query),
  });
}

// ── 会话 ───────────────────────────────────────

export function useSessions(agentId?: string) {
  return useQuery({
    queryKey: queryKeys.sessions.list(agentId),
    queryFn: () => sessionsApi.listSessions(agentId),
  });
}

export function useSessionMessages(sessionId: string | undefined, limit = 100) {
  return useQuery({
    queryKey: queryKeys.sessions.messages(sessionId ?? "", limit),
    queryFn: () => sessionsApi.getSessionMessages(sessionId as string, limit),
    enabled: Boolean(sessionId),
  });
}

// ── 记忆 ───────────────────────────────────────

export function useMemoryEpisodes(agentId: string | undefined, limit = 50) {
  return useQuery({
    queryKey: queryKeys.memory.episodes(agentId ?? "", limit),
    queryFn: () => memoryApi.listEpisodes(agentId as string, limit),
    enabled: Boolean(agentId),
  });
}

export function useMemoryProfiles(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.memory.profiles(agentId ?? ""),
    queryFn: () => memoryApi.listProfiles(agentId as string),
    enabled: Boolean(agentId),
  });
}

export function useMemoryJargon(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.memory.jargon(agentId ?? ""),
    queryFn: () => memoryApi.listJargon(agentId as string),
    enabled: Boolean(agentId),
  });
}

export function useMemoryItems(agentId: string | undefined, limit = 200, offset = 0) {
  return useQuery({
    queryKey: queryKeys.memory.items(agentId ?? "", limit, offset),
    queryFn: () => memoryApi.listMemoryItems(agentId as string, { limit, offset }),
    enabled: Boolean(agentId),
  });
}

// ── SubAgent / 审批 ────────────────────────────

export function useSubAgentRuns() {
  return useQuery({ queryKey: queryKeys.tasks.list(), queryFn: subagentApi.listAllSubAgentRuns });
}

export function useAgentSubAgentRuns(agentId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.agents.subagentRuns(agentId ?? ""),
    queryFn: () => subagentApi.listSubAgentRuns(agentId as string),
    enabled: Boolean(agentId),
  });
}

export function useSubAgentEvents(taskId: string | undefined, afterSeq = 0, limit = 100) {
  return useQuery({
    queryKey: queryKeys.tasks.events(taskId ?? "", afterSeq, limit),
    queryFn: () => subagentApi.getSubAgentEvents(taskId as string, { afterSeq, limit }),
    enabled: Boolean(taskId),
  });
}

export function useApprovals() {
  return useQuery({
    queryKey: queryKeys.approvals.pending(),
    queryFn: subagentApi.listApprovals,
    refetchInterval: 10_000,
  });
}

export function useApprovalHistory(limit = 100) {
  return useQuery({
    queryKey: queryKeys.approvals.history(limit),
    queryFn: () => subagentApi.getApprovalHistory(limit),
  });
}

// ── 配置 ───────────────────────────────────────

export function useConfigSchema() {
  return useQuery({
    queryKey: queryKeys.config.schema(),
    queryFn: configApi.getConfigSchema,
    staleTime: STATIC_STALE,
    refetchOnWindowFocus: false,
  });
}

export function useGlobalConfig() {
  return useQuery({ queryKey: queryKeys.config.global(), queryFn: configApi.getGlobalConfig });
}

// ── Webhook / 租户 / 身份 / 工作流 ─────────────

export function useWebhooks(event?: string) {
  return useQuery({
    queryKey: queryKeys.webhooks.list(event),
    queryFn: () => governanceApi.listWebhooks(event),
  });
}

export function useTenants(organization?: string) {
  return useQuery({
    queryKey: queryKeys.tenants.list(organization),
    queryFn: () => governanceApi.listTenants(organization),
  });
}

export function useIdentityConflicts() {
  return useQuery({ queryKey: queryKeys.identity.conflicts(), queryFn: governanceApi.listIdentityConflicts });
}

export function useWorkflows() {
  return useQuery({ queryKey: queryKeys.workflows.list(), queryFn: governanceApi.listWorkflows });
}
