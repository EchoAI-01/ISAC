/** 用量与成本端点 (routes_usage.py)。
 *
 * 口径 (SPEC §8.5 / §九 Usage+Cost):
 * - summary/timeseries 返回**数组** (v1 内置 WebUI 误当对象, 明细表恒空);
 * - `estimated_cost_sum` 是字符串 (SQL SUM 后 6 位小数) 或 null;
 *   组内价格全未知时为 null —— **不得伪造成 0**;
 * - events 需要 `usage:detail` scope, 聚合只需 `usage:read`;
 * - 计量未启用 (observability.usage.enabled=false) 时整组路由不挂载 → unavailable。
 */

import { client, unwrap } from "./client";
import type { UsageEventRow, UsageGroupBy, UsageSummaryRow } from "./types";

export interface UsageFilter {
  /** epoch 秒。 */
  from?: number;
  to?: number;
  provider?: string;
  model?: string;
  agent_id?: string;
  session_id?: string;
  modality?: string;
  status?: string;
}

export interface UsageSummaryQuery extends UsageFilter {
  /** 多个维度用逗号拼接 (后端按白名单拆分)。 */
  group_by?: UsageGroupBy | UsageGroupBy[];
}

export interface UsageTimeseriesQuery extends UsageSummaryQuery {
  bucket?: "hour" | "day";
}

function serializeGroupBy(groupBy: UsageSummaryQuery["group_by"]): string | undefined {
  if (!groupBy) return undefined;
  return Array.isArray(groupBy) ? groupBy.join(",") : groupBy;
}

export function getUsageSummary(query: UsageSummaryQuery = {}): Promise<UsageSummaryRow[]> {
  const { group_by, ...rest } = query;
  return unwrap<UsageSummaryRow[]>(
    client.GET("/api/v1/usage/models/summary", {
      params: { query: { ...rest, group_by: serializeGroupBy(group_by) } },
    }),
    "/api/v1/usage/models/summary",
  );
}

export function getUsageEvents(
  query: UsageFilter & { limit?: number; offset?: number } = {},
): Promise<UsageEventRow[]> {
  return unwrap<UsageEventRow[]>(
    client.GET("/api/v1/usage/models/events", { params: { query } }),
    "/api/v1/usage/models/events",
  );
}

export function getUsageTimeseries(query: UsageTimeseriesQuery = {}): Promise<UsageSummaryRow[]> {
  const { group_by, ...rest } = query;
  return unwrap<UsageSummaryRow[]>(
    client.GET("/api/v1/usage/models/timeseries", {
      params: { query: { ...rest, group_by: serializeGroupBy(group_by) } },
    }),
    "/api/v1/usage/models/timeseries",
  );
}

/** 成本字符串 → 数字; null/未知价格返回 null (不伪造 0)。 */
export function parseCost(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}
