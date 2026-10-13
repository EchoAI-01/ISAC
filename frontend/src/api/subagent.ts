/** SubAgent 任务与 HITL 审批端点 (routes_subagent.py + routes_approvals.py)。
 *
 * SPEC §8.4 隐私边界: 接口不返回模型原始 reasoning / 密钥 / 完整文件内容;
 * 前端只渲染 summary 与 evidence_ref, 不臆造未返回的字段。
 * 取消是幂等请求: 任务已进终态时返回原终态, **不代表取消成功** —— UI 必须
 * 按返回的 status 判定, 不能一律提示"已取消"。
 */

import { client, unwrap } from "./client";
import type {
  ApprovalDecisionRecord,
  ApprovalRequest,
  StatusResult,
  SubAgentEvent,
  SubAgentEventsResult,
  SubAgentRun,
} from "./types";

export function createSubAgentRun(
  agentId: string,
  payload: { objective: string; summary?: string; session_id?: string; trace_id?: string },
): Promise<{ task_id: string; status: string }> {
  return unwrap<{ task_id: string; status: string }>(
    client.POST("/api/v1/agents/{agent_id}/subagent-runs", {
      params: { path: { agent_id: agentId } },
      body: payload,
    }),
    `/api/v1/agents/${agentId}/subagent-runs`,
  );
}

export function listSubAgentRuns(agentId: string): Promise<SubAgentRun[]> {
  return unwrap<SubAgentRun[]>(
    client.GET("/api/v1/agents/{agent_id}/subagent-runs", {
      params: { path: { agent_id: agentId } },
    }),
    `/api/v1/agents/${agentId}/subagent-runs`,
  );
}

/** 全局任务列表 (Sessions & Tasks 页主视图)。 */
export function listAllSubAgentRuns(): Promise<SubAgentRun[]> {
  return unwrap<SubAgentRun[]>(client.GET("/api/v1/subagent-runs"), "/api/v1/subagent-runs");
}

export function getSubAgentRun(taskId: string): Promise<SubAgentRun> {
  return unwrap<SubAgentRun>(
    client.GET("/api/v1/subagent-runs/{task_id}", { params: { path: { task_id: taskId } } }),
    `/api/v1/subagent-runs/${taskId}`,
  );
}

export function getSubAgentEvents(
  taskId: string,
  opts: { afterSeq?: number; limit?: number } = {},
): Promise<SubAgentEventsResult> {
  return unwrap<SubAgentEventsResult>(
    client.GET("/api/v1/subagent-runs/{task_id}/events", {
      params: {
        path: { task_id: taskId },
        query: { after_seq: opts.afterSeq ?? 0, limit: opts.limit ?? 100 },
      },
    }),
    `/api/v1/subagent-runs/${taskId}/events`,
  );
}

export function cancelSubAgentRun(taskId: string): Promise<SubAgentRun> {
  return unwrap<SubAgentRun>(
    client.POST("/api/v1/subagent-runs/{task_id}/cancel", {
      params: { path: { task_id: taskId } },
    }),
    `/api/v1/subagent-runs/${taskId}/cancel`,
  );
}

/** 任务终态集合 (与后端 SubAgentRun 终态口径一致, 用于禁用取消按钮)。 */
export const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "canceled",
  "aborted",
  "timeout",
]);

export function isTerminalStatus(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(String(status).toLowerCase());
}

// ── HITL 审批 (U5) ──────────────────────────────

export function listApprovals(): Promise<{ approvals: ApprovalRequest[] }> {
  return unwrap<{ approvals: ApprovalRequest[] }>(
    client.GET("/api/v1/approvals"),
    "/api/v1/approvals",
  );
}

/** 决策留痕: U1 事件表全部 tool.* 记录 (decision/decider/reason)。 */
export function getApprovalHistory(limit = 100): Promise<{ events: ApprovalDecisionRecord[] }> {
  return unwrap<{ events: ApprovalDecisionRecord[] }>(
    client.GET("/api/v1/approvals/history", { params: { query: { limit } } }),
    "/api/v1/approvals/history",
  );
}

/**
 * 裁决 ask 档高危工具调用。
 *
 * 后端 404 = 审批不存在或已过期 (超时 fail-closed 拒绝); 审批门未接线时
 * ask 档直接拒绝, 本端点整体不挂载 → unavailable。
 */
export function decideApproval(
  approvalId: string,
  decision: "approved" | "rejected",
): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.POST("/api/v1/approvals/{approval_id}/decide", {
      params: { path: { approval_id: approvalId } },
      body: { decision },
    }),
    `/api/v1/approvals/${approvalId}/decide`,
  );
}

export type { SubAgentEvent };
