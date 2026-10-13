/** 系统面端点: 审计 / 指标 / 实时日志 SSE (F3)。
 *
 * scope 口径: tokens[] 模式下 `/audit` 与 `/logs/tail` 都要求 `"*"` 通配
 * (审计与系统日志是最敏感数据面) —— 窄 scope token 会拿到 403 SCOPE_FORBIDDEN,
 * 页面渲染 permission-denied 并说明所需 scope, 不静默显示空表。
 */

import { client, rawRequest, unwrap } from "./client";
import { connectSse, type SseConnection, type SseOptions } from "./sse";
import type { AuditEntry, LogEntry, LogLevel, MetricsSnapshot } from "./types";

export interface AuditQuery {
  action?: string;
  actor?: string;
  path_prefix?: string;
  limit?: number;
}

/** 审计日志 (最新到最旧)。 */
export function queryAudit(query: AuditQuery = {}): Promise<AuditEntry[]> {
  return unwrap<AuditEntry[]>(
    client.GET("/api/v1/audit", { params: { query } }),
    "/api/v1/audit",
  );
}

/** JSON 指标快照 (需认证)。 */
export function getMetricsSnapshot(): Promise<MetricsSnapshot> {
  return unwrap<MetricsSnapshot>(client.GET("/api/v1/metrics"), "/api/v1/metrics");
}

/** Prometheus 文本指标 (默认免认证; metrics_auth_enabled=true 时需认证)。 */
export async function getPrometheusText(signal?: AbortSignal): Promise<string> {
  const response = await rawRequest("GET", "/metrics", { signal });
  return response.text();
}

export const LOG_LEVELS: LogLevel[] = ["debug", "info", "warning", "error", "critical"];

export interface LogTailOptions {
  /** 只推该级别及以上 (服务端过滤, 客户端不二次过滤)。 */
  level?: LogLevel | "";
  /** 心跳间隔秒 (默认服务端 10s)。 */
  heartbeatSeconds?: number;
  /** 测试/一次性抓取用: 发 N 帧后服务端结束流。 */
  maxChunks?: number;
  lastEventId?: string;
  onEntry: (entry: LogEntry) => void;
  onOpen?: SseOptions["onOpen"];
  onError?: SseOptions["onError"];
  onClose?: SseOptions["onClose"];
  onHeartbeat?: SseOptions["onHeartbeat"];
  signal?: AbortSignal;
  maxRetries?: number;
}

/**
 * 实时日志台 SSE (GET /api/v1/logs/tail)。
 *
 * 用 fetch 流式实现而非 EventSource: Bearer 轨也能带 Authorization 头
 * (EventSource 不支持自定义头, v1 内置 WebUI 因此在 Bearer 模式下直接禁用日志台)。
 */
export function tailLogs(options: LogTailOptions): SseConnection {
  const { level, heartbeatSeconds, maxChunks, onEntry, ...rest } = options;
  return connectSse({
    path: "/api/v1/logs/tail",
    query: {
      level: level || undefined,
      heartbeat_seconds: heartbeatSeconds,
      max_chunks: maxChunks,
    },
    onEvent: (event) => {
      // 服务端帧格式: id=<_seq> event=log data=<json entry>
      try {
        onEntry(JSON.parse(event.data) as LogEntry);
      } catch {
        // 非 JSON 帧 (理论上不出现): 原样作为 event 文本呈现, 不丢日志。
        onEntry({ _seq: Number(event.id) || 0, _ts: event.receivedAt, event: event.data });
      }
    },
    ...rest,
  });
}
