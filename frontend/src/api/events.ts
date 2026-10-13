/** 事件流 SSE (GET /api/v1/events/stream, F3)。
 *
 * 后端语义 (routes_events.py + CONTROL_PLANE_SPEC §8.3 状态注):
 * - 桥接 EventBus **全部**事件, 事件名取 payload 的 `event_type` 字段;
 *   未登记者落 `unknown` 兜底名, **仅 `"*"` 通配 scope 可见** (fail-closed);
 * - 生产事件 (POST_MESSAGE / ON_START) 均不带 event_type → 以 `unknown` 发出,
 *   因此窄 scope token 常常"什么都看不到": UI 必须解释这一点, 不能显示成
 *   "暂无事件" 让用户以为系统静默;
 * - §8.3 目录里的 agent.status_changed 等多数事件**尚无生产者**, 属预留。
 */

import { connectSse, type SseConnection, type SseOptions } from "./sse";

export interface StreamEvent {
  /** SSE id (服务端递增 seq), 断线恢复用。 */
  id: string;
  /** 事件名 (payload.event_type 或 "unknown")。 */
  name: string;
  /** 解析后的 payload; 解析失败时为原始字符串。 */
  payload: unknown;
  receivedAt: number;
}

export interface EventStreamOptions {
  heartbeatSeconds?: number;
  /** 测试/一次性抓取: 发 N 帧后服务端结束流。 */
  maxChunks?: number;
  lastEventId?: string;
  onEvent: (event: StreamEvent) => void;
  onOpen?: SseOptions["onOpen"];
  onError?: SseOptions["onError"];
  onClose?: SseOptions["onClose"];
  onHeartbeat?: SseOptions["onHeartbeat"];
  signal?: AbortSignal;
  maxRetries?: number;
}

export function streamEvents(options: EventStreamOptions): SseConnection {
  const { heartbeatSeconds, maxChunks, onEvent, ...rest } = options;
  return connectSse({
    path: "/api/v1/events/stream",
    query: { heartbeat_seconds: heartbeatSeconds, max_chunks: maxChunks },
    onEvent: (frame) => {
      let payload: unknown = frame.data;
      try {
        payload = JSON.parse(frame.data);
      } catch {
        // payload 非 JSON 时保留原始字符串 (不丢事件)。
      }
      onEvent({
        id: frame.id,
        name: frame.event || "unknown",
        payload,
        receivedAt: frame.receivedAt,
      });
    },
    ...rest,
  });
}

/** SPEC §8.3 目录事件 (多数尚无生产者, UI 需标注"目录预留")。 */
export const EVENT_CATALOG = [
  "agent.status_changed",
  "channel.status_changed",
  "provider.health_changed",
  "task.progress",
  "model.usage_recorded",
  "alert.triggered",
  "audit.created",
] as const;

/** 无需 scope 收窄即可见的公开事件 (其余未登记类型仅 "*" 可见)。 */
export const PUBLIC_EVENT_TYPES = new Set(["channel.status_changed"]);
