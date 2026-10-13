/** 写操作 hooks (mutation + 缓存失效 + 统一反馈)。
 *
 * 约定 (SPEC §8.2):
 * - 写成功必须失效相关读缓存, 否则页面显示陈旧数据;
 * - 失败必须把**后端错误码与消息**原样反馈 (不吞成"操作失败");
 * - 409 CONFIG_CONFLICT 不自动重试 —— 由调用方 (配置编辑事务) 打开冲突面板;
 * - 高影响操作的二次确认在页面层用 <ConfirmDialog>, mutation 只负责执行。
 */

import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import * as agentsApi from "@/api/agents";
import * as configApi from "@/api/config";
import * as governanceApi from "@/api/governance";
import * as memoryApi from "@/api/memory";
import * as pluginsApi from "@/api/plugins";
import * as providersApi from "@/api/providers";
import * as routingApi from "@/api/routing";
import * as subagentApi from "@/api/subagent";
import { errorMessage, isApiError } from "@/api/errors";
import type { AgentConfig, PluginInstallSource } from "@/api/types";
import { useToast } from "@/components/Toast";
import { queryKeys } from "./queryKeys";

interface ApiMutationConfig<TVars, TResult> {
  mutationFn: (vars: TVars) => Promise<TResult>;
  /** 成功后失效的缓存键 (前缀匹配)。 */
  invalidates?: QueryKey[];
  success?: string | ((result: TResult, vars: TVars) => string);
  successDescription?: string | ((result: TResult, vars: TVars) => string | undefined);
  failure?: string | ((error: unknown, vars: TVars) => string);
  onSuccess?: (result: TResult, vars: TVars) => void;
  onError?: (error: unknown, vars: TVars) => void;
}

/** 统一封装: 失效 + Toast + 回调。 */
export function useApiMutation<TVars, TResult>(config: ApiMutationConfig<TVars, TResult>) {
  const queryClient = useQueryClient();
  const toast = useToast();

  return useMutation<TResult, Error, TVars>({
    mutationFn: config.mutationFn,
    onSuccess: (result, vars) => {
      for (const key of config.invalidates ?? []) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      const title = typeof config.success === "function" ? config.success(result, vars) : config.success;
      if (title) {
        const description =
          typeof config.successDescription === "function"
            ? config.successDescription(result, vars)
            : config.successDescription;
        toast.success(title, description);
      }
      config.onSuccess?.(result, vars);
    },
    onError: (error, vars) => {
      const title = typeof config.failure === "function" ? config.failure(error, vars) : (config.failure ?? "操作失败");
      const code = isApiError(error) ? error.code : "";
      toast.error(title, code ? `${errorMessage(error)} (${code})` : errorMessage(error));
      config.onError?.(error, vars);
    },
  });
}

// ── Agent ──────────────────────────────────────

export function useCreateAgent() {
  return useApiMutation({
    mutationFn: (payload: Parameters<typeof agentsApi.createAgent>[0]) => agentsApi.createAgent(payload),
    invalidates: [queryKeys.agents.all, queryKeys.health],
    success: (_result, vars) => `Agent ${vars.agent_id} 已创建`,
    successDescription:
      "创建走受限默认模板: 请求里的 tools_policy / plugins_allow / mcp_servers 等能力字段被后端丢弃, 需要在详情页 PATCH 显式授予。",
  });
}

export function useAgentLifecycle() {
  const invalidate: QueryKey[] = [queryKeys.agents.all, queryKeys.health];
  const start = useApiMutation({
    mutationFn: (id: string) => agentsApi.startAgent(id),
    invalidates: invalidate,
    success: (_r, id) => `Agent ${id} 已启动`,
  });
  const stop = useApiMutation({
    mutationFn: (id: string) => agentsApi.stopAgent(id),
    invalidates: invalidate,
    success: (_r, id) => `Agent ${id} 已停止`,
  });
  const destroy = useApiMutation({
    mutationFn: ({ id, keepMemory }: { id: string; keepMemory: boolean }) => agentsApi.destroyAgent(id, keepMemory),
    invalidates: [...invalidate, queryKeys.memory.all, queryKeys.sessions.all],
    success: (_r, vars) => `Agent ${vars.id} 已销毁`,
    successDescription: (_r, vars) =>
      vars.keepMemory ? "记忆数据已保留 (keep_memory=true)。" : "该 Agent 命名空间下的记忆已一并清理。",
  });
  return { start, stop, destroy };
}

export function usePatchAgent() {
  return useApiMutation({
    mutationFn: ({
      agentId,
      patch,
      ifMatch,
    }: {
      agentId: string;
      patch: Partial<AgentConfig>;
      ifMatch?: number;
    }) => agentsApi.patchAgent(agentId, patch, ifMatch),
    invalidates: [queryKeys.agents.all, queryKeys.config.all],
    success: (_result, vars) => `Agent ${vars.agentId} 配置已更新`,
    successDescription: (result) => `新 revision = ${result.revision}`,
  });
}

export function usePutPluginMatrix(agentId: string) {
  return useApiMutation({
    mutationFn: (matrix: { plugins_allow: string[]; plugins_deny: string[] }) =>
      agentsApi.putPluginMatrix(agentId, matrix),
    invalidates: [queryKeys.agents.pluginMatrix(agentId), queryKeys.agents.config(agentId), queryKeys.plugins.all],
    success: () => `Agent ${agentId} 插件矩阵已更新`,
    successDescription: "已按启用矩阵同步到运行中实例 (D5: 绕过 allow/deny 的路径已封堵)。",
  });
}

// ── 路由 / Link ────────────────────────────────

export function usePutRoutingRules() {
  return useApiMutation({
    mutationFn: (rules: Parameters<typeof routingApi.putRoutingRules>[0]) => routingApi.putRoutingRules(rules),
    invalidates: [queryKeys.routing.all],
    success: () => "路由规则已更新",
    successDescription: (_result, rules) =>
      `${rules.bindings.length} 条绑定, ${Object.keys(rules.default_agents).length} 个平台默认 Agent (已持久化 data/routing.jsonc)。`,
  });
}

export function useAddLink() {
  return useApiMutation({
    mutationFn: (link: Parameters<typeof routingApi.addLink>[0]) => routingApi.addLink(link),
    invalidates: [queryKeys.routing.links()],
    success: (_r, link) => `Link ${link.from_agent} → ${link.to_agent} 已创建`,
    successDescription:
      "permissions 为空时 notify/handoff/memory_query 全部拒绝 (deny-by-default), 仅 ask 可用。",
  });
}

export function useRemoveLink() {
  return useApiMutation({
    mutationFn: ({ from, to }: { from: string; to: string }) => routingApi.removeLink(from, to),
    invalidates: [queryKeys.routing.links()],
    success: (_r, vars) => `Link ${vars.from} → ${vars.to} 已删除`,
  });
}

// ── 插件 (F4) ──────────────────────────────────

const PLUGIN_INVALIDATIONS: QueryKey[] = [queryKeys.plugins.all, queryKeys.agents.all];

export function useInstallPlugin() {
  return useApiMutation({
    mutationFn: (source: PluginInstallSource) => pluginsApi.installPlugin(source),
    invalidates: PLUGIN_INVALIDATIONS,
    success: (result) => `安装结果: ${result.status}`,
    successDescription: (result) => {
      const synced = Object.entries(result.sync ?? {});
      return synced.length > 0
        ? `已同步到 ${synced.length} 个运行中 Agent (D5: 经启用矩阵过滤)。`
        : "未同步到运行中 Agent (可能没有运行中实例, 或插件未提供工具)。";
    },
  });
}

export function useReloadPlugin() {
  return useApiMutation({
    mutationFn: (name: string) => pluginsApi.reloadPlugin(name),
    invalidates: PLUGIN_INVALIDATIONS,
    success: (_r, name) => `插件 ${name} 已热重载`,
  });
}

export function useUninstallPlugin() {
  return useApiMutation({
    mutationFn: (name: string) => pluginsApi.uninstallPlugin(name),
    invalidates: PLUGIN_INVALIDATIONS,
    success: (_r, name) => `插件 ${name} 已卸载`,
    successDescription: "共享注册表与运行中 Agent 的来源条目已清理。",
  });
}

export function useRetryPlugin() {
  return useApiMutation({
    mutationFn: (name: string) => pluginsApi.retryPlugin(name),
    invalidates: PLUGIN_INVALIDATIONS,
    success: (result) => `重试结果: ${result.status}`,
    failure: (_error, name) => `插件 ${name} 重试失败`,
  });
}

// ── Provider / 制品 ────────────────────────────

export function useTestProvider() {
  return useApiMutation({
    mutationFn: ({ providerId, modelId }: { providerId: string; modelId?: string }) =>
      providersApi.testProvider(providerId, modelId ?? ""),
    invalidates: [queryKeys.providers.all],
    success: (_r, vars) => `Provider ${vars.providerId} 连通性测试通过`,
  });
}

export function useDeleteArtifact() {
  return useApiMutation({
    mutationFn: (artifactId: string) => providersApi.deleteArtifact(artifactId),
    invalidates: [queryKeys.artifacts.all],
    success: () => "制品已删除",
  });
}

// ── 记忆治理 ───────────────────────────────────

type GovernanceAction = "freeze" | "protect" | "correct" | "delete" | "restore";

const GOVERNANCE_FN: Record<GovernanceAction, (agentId: string, itemId: string, content?: string) => Promise<unknown>> = {
  freeze: (a, i) => memoryApi.freezeMemoryItem(a, i),
  protect: (a, i) => memoryApi.protectMemoryItem(a, i),
  correct: (a, i, content) => memoryApi.correctMemoryItem(a, i, content ?? ""),
  delete: (a, i) => memoryApi.deleteMemoryItem(a, i),
  restore: (a, i) => memoryApi.restoreMemoryItem(a, i),
};

const GOVERNANCE_LABEL: Record<GovernanceAction, string> = {
  freeze: "冻结",
  protect: "保护",
  correct: "纠正",
  delete: "删除",
  restore: "恢复",
};

/**
 * 记忆治理操作 (freeze/protect/correct/delete/restore)。
 *
 * 治理端点用 `{ok:false, detail}` 表达"条目不存在/受保护拒绝", HTTP 仍是 200 ——
 * 必须按 ok 反馈 (warning 而非 success), 否则用户会以为操作已生效。
 */
export function useGovernanceAction(agentId: string) {
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ action, itemId, content }: { action: GovernanceAction; itemId: string; content?: string }) =>
      GOVERNANCE_FN[action](agentId, itemId, content) as Promise<{ ok: boolean; detail: string }>,
    onSuccess: (result, vars) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.memory.all });
      if (result.ok) toast.success(`${GOVERNANCE_LABEL[vars.action]}成功`, result.detail);
      else toast.warning(`${GOVERNANCE_LABEL[vars.action]}未生效`, result.detail);
    },
    onError: (error) => toast.error("记忆治理操作失败", errorMessage(error)),
  });
}

// ── SubAgent / 审批 ────────────────────────────

export function useCancelSubAgentRun() {
  return useApiMutation({
    mutationFn: (taskId: string) => subagentApi.cancelSubAgentRun(taskId),
    invalidates: [queryKeys.tasks.all, queryKeys.agents.all],
    // 取消是幂等请求: 已终态时返回原终态, 不代表本次取消生效。
    success: (result) =>
      subagentApi.isTerminalStatus(result.status) && result.status !== "cancelled"
        ? `任务已处于终态: ${result.status}`
        : "取消请求已受理",
    successDescription: (result) => `task_id=${result.task_id}, status=${result.status}`,
  });
}

export function useDecideApproval() {
  return useApiMutation({
    mutationFn: ({ approvalId, decision }: { approvalId: string; decision: "approved" | "rejected" }) =>
      subagentApi.decideApproval(approvalId, decision),
    invalidates: [queryKeys.approvals.all, queryKeys.tasks.all],
    success: (_r, vars) => (vars.decision === "approved" ? "已批准该工具调用" : "已拒绝该工具调用"),
    failure: () => "审批决策失败 (可能已过期或超时 fail-closed 拒绝)",
  });
}

// ── 配置 (F2 编辑事务) ─────────────────────────

export function usePatchGlobalConfig() {
  return useApiMutation({
    mutationFn: ({ patch, ifMatch }: { patch: Record<string, unknown>; ifMatch?: number }) =>
      configApi.patchGlobalConfig(patch, ifMatch),
    invalidates: [queryKeys.config.all, queryKeys.agents.all, queryKeys.health],
    // 结果文案由页面按 applied/restart_required 细化 (§8.2 规则 6: 不假装热更成功),
    // 这里只失效缓存, 不弹通用成功提示。
  });
}

export function useReloadGlobalConfig() {
  return useApiMutation({
    mutationFn: () => configApi.reloadGlobalConfig(),
    invalidates: [queryKeys.config.all, queryKeys.agents.all, queryKeys.health],
    success: () => "已从磁盘重读配置并热应用",
    successDescription: (result) =>
      `applied: ${result.applied.join(", ") || "—"}; restart_required: ${result.restart_required.join(", ") || "—"}`,
  });
}

// ── Webhook / 租户 / 身份 / 工作流 ─────────────

export function useSubscribeWebhook() {
  return useApiMutation({
    mutationFn: ({ event, url }: { event: string; url: string }) => governanceApi.subscribeWebhook(event, url),
    invalidates: [queryKeys.webhooks.all],
    success: (_r, vars) => `已订阅 ${vars.event}`,
  });
}

export function useUnsubscribeWebhook() {
  return useApiMutation({
    mutationFn: ({ event, url }: { event: string; url: string }) => governanceApi.unsubscribeWebhook(event, url),
    invalidates: [queryKeys.webhooks.all],
    success: (_r, vars) => `已取消订阅 ${vars.event}`,
  });
}

export function useTriggerAutomation() {
  return useApiMutation({
    mutationFn: ({ event, data }: { event: string; data?: Record<string, unknown> }) =>
      governanceApi.triggerAutomation(event, data ?? {}),
    invalidates: [queryKeys.webhooks.all, queryKeys.auditAll],
    success: (result) => `已触发 ${result.event}`,
    successDescription: (result) => {
      const entries = Object.entries(result.delivered ?? {});
      if (entries.length === 0) return "无订阅者, 未投递。";
      const failed = entries.filter(([, status]) => !String(status).startsWith("ok"));
      return `投递 ${entries.length} 个目标, 失败 ${failed.length} 个。`;
    },
  });
}

export function useCreateTenant() {
  return useApiMutation({
    mutationFn: (payload: Parameters<typeof governanceApi.createTenant>[0]) => governanceApi.createTenant(payload),
    invalidates: [queryKeys.tenants.all],
    success: (result) => `租户 ${result.tenant_id} 已创建`,
  });
}

export function useDeleteTenant() {
  return useApiMutation({
    mutationFn: (tenantId: string) => governanceApi.deleteTenant(tenantId),
    invalidates: [queryKeys.tenants.all, queryKeys.memory.all],
    success: (_r, tenantId) => `租户 ${tenantId} 已删除`,
    successDescription: "数据面打标行已按级联清理 (best-effort, 失败项见服务端日志)。",
  });
}

export function useTenantMembers(tenantId: string) {
  const add = useApiMutation({
    mutationFn: ({ memberId, memberType }: { memberId: string; memberType?: string }) =>
      governanceApi.addTenantMember(tenantId, memberId, memberType ?? "user"),
    invalidates: [queryKeys.tenants.all],
    success: (_r, vars) => `成员 ${vars.memberId} 已加入租户`,
  });
  const remove = useApiMutation({
    mutationFn: ({ memberId, memberType }: { memberId: string; memberType?: string }) =>
      governanceApi.removeTenantMember(tenantId, memberId, memberType ?? "user"),
    invalidates: [queryKeys.tenants.all],
    success: (_r, vars) => `成员 ${vars.memberId} 已移出租户`,
  });
  return { add, remove };
}

export function useBindIdentity() {
  return useApiMutation({
    mutationFn: (payload: Parameters<typeof governanceApi.bindIdentity>[0]) => governanceApi.bindIdentity(payload),
    invalidates: [queryKeys.identity.all, queryKeys.memory.all],
    success: (_r, vars) => `已绑定 ${vars.platform}:${vars.platform_user_id} → ${vars.person_id}`,
  });
}

export function useResolveConflict() {
  return useApiMutation({
    mutationFn: ({ conflictId, personId }: { conflictId: string; personId: string }) =>
      governanceApi.resolveIdentityConflict(conflictId, personId),
    invalidates: [queryKeys.identity.all, queryKeys.memory.all],
    success: (_r, vars) => `冲突 ${vars.conflictId} 已裁决为 ${vars.personId}`,
  });
}

export function useStartWorkflow() {
  return useApiMutation({
    mutationFn: (workflowId: string) => governanceApi.startWorkflow(workflowId),
    invalidates: [queryKeys.workflows.all, queryKeys.tasks.all],
    success: (_r, workflowId) => `工作流 ${workflowId} 已启动`,
  });
}
