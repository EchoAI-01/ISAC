import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { SseConnection } from "@/api/sse";

/**
 * SSE 消费 hook (F3: 实时日志台 + 事件流)。
 *
 * 三个工程约束 (CONTROL_PLANE_SPEC §8.3 "日志按需订阅并设置速率和行数上限"):
 * 1. **行数上限**: 环形缓冲, 超过 maxItems 丢最旧 (并计数 dropped, UI 明示);
 * 2. **速率限制**: 事件先进 ref 缓冲, 按 flushIntervalMs 批量刷进 state ——
 *    高频日志下不会每条都触发一次 React 渲染 (v1 内置 WebUI 是逐条 setState +
 *    字符串拼接, 日志一多主线程直接卡死);
 * 3. **暂停不丢事件**: pause 关闭连接并记住 Last-Event-ID, resume 重连时带上,
 *    由服务端回放断线期间的缓冲 (routes_logs/routes_events 都支持)。
 */

export interface SseHandlers<T> {
  onEvent: (event: T) => void;
  onOpen?: () => void;
  onError?: (error: unknown, willRetry: boolean) => void;
  onClose?: () => void;
  onHeartbeat?: () => void;
  lastEventId?: string;
}

export type SsePhase = "idle" | "connecting" | "open" | "paused" | "retrying" | "closed" | "error";

export interface UseSseOptions<T> {
  /** 连接工厂 (页面传入 tailLogs / streamEvents 的偏函数)。 */
  create: (handlers: SseHandlers<T>) => SseConnection;
  /** 是否建立连接 (false = 不连, 用于"离开 tab 即断开")。 */
  enabled?: boolean;
  maxItems?: number;
  flushIntervalMs?: number;
  /**
   * 重连键: 值变化时断开并按当前 Last-Event-ID 重连 (不清空已收内容)。
   * 用于 level 过滤一类"服务端参数变了必须重连"的场景 —— 比 remount 组件好,
   * 因为服务端会从 Last-Event-ID 之后回放, 既不重复也不丢。
   */
  reconnectKey?: unknown;
}

export interface UseSseResult<T> {
  items: T[];
  phase: SsePhase;
  paused: boolean;
  error: string | null;
  totalReceived: number;
  dropped: number;
  lastEventId: string;
  lastHeartbeatAt: number | null;
  pause: () => void;
  resume: () => void;
  clear: () => void;
  /** 记录服务端帧 id (供 pause→resume 时带 Last-Event-ID 续传)。 */
  trackLastEventId: (id: string) => void;
}

export function useSse<T>(options: UseSseOptions<T>): UseSseResult<T> {
  const { create, enabled = true, maxItems = 2000, flushIntervalMs = 150, reconnectKey } = options;

  const [items, setItems] = useState<T[]>([]);
  const [phase, setPhase] = useState<SsePhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState({ totalReceived: 0, dropped: 0 });
  const [lastEventId, setLastEventId] = useState("");
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState<number | null>(null);
  const [paused, setPaused] = useState(false);

  const buffer = useRef<T[]>([]);
  const connection = useRef<SseConnection | null>(null);
  const flushTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pausedRef = useRef(false);
  const lastIdRef = useRef("");
  const statsRef = useRef({ totalReceived: 0, dropped: 0 });
  // create 是每次渲染新建的闭包, 存 ref 避免 effect 反复重连;
  // ref 写入放在 effect 里 (渲染期间写 ref 不纯, react-hooks 编译器规则禁止)。
  const createRef = useRef(create);
  useEffect(() => {
    createRef.current = create;
  });

  const flush = useCallback(() => {
    if (buffer.current.length === 0) return;
    const pending = buffer.current;
    buffer.current = [];
    setItems((current) => {
      const merged = current.concat(pending);
      if (merged.length <= maxItems) return merged;
      return merged.slice(merged.length - maxItems);
    });
  }, [maxItems]);

  // 批量刷新定时器 (仅在连接期间运行)。
  useEffect(() => {
    if (!enabled) return;
    flushTimer.current = setInterval(flush, flushIntervalMs);
    return () => {
      if (flushTimer.current) clearInterval(flushTimer.current);
      flushTimer.current = null;
    };
  }, [enabled, flush, flushIntervalMs]);

  useEffect(() => {
    if (!enabled) {
      connection.current?.close();
      connection.current = null;
      // 不 setState: phase 对外按 enabled 派生成 "idle" (见返回值), 避免 effect 内同步 setState。
      return;
    }
    if (pausedRef.current) return;

    // 继承上一条连接的 Last-Event-ID: 服务端从该 id 之后回放, 重连不重不漏。
    const inherited = connection.current?.lastEventId;
    if (inherited) lastIdRef.current = inherited;
    connection.current?.close();

    setPhase("connecting");
    setError(null);
    const handle = createRef.current({
      lastEventId: lastIdRef.current || undefined,
      onOpen: () => setPhase("open"),
      onEvent: (event) => {
        statsRef.current = { ...statsRef.current, totalReceived: statsRef.current.totalReceived + 1 };
        if (buffer.current.length >= maxItems) {
          const overflow = buffer.current.length - maxItems + 1;
          buffer.current.splice(0, overflow);
          statsRef.current = { ...statsRef.current, dropped: statsRef.current.dropped + overflow };
        }
        buffer.current.push(event);
        setStats(statsRef.current);
      },
      onError: (err, willRetry) => {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setPhase(willRetry ? "retrying" : "error");
      },
      onClose: () => {
        if (!pausedRef.current) setPhase((current) => (current === "error" ? current : "closed"));
      },
      onHeartbeat: () => {
        setLastHeartbeatAt(Date.now() / 1000);
        setPhase((current) => (current === "open" || current === "connecting" ? "open" : current));
      },
    });
    connection.current = handle;

    return () => {
      // 断开前记下最后收到的帧 id, 供下次连接 (reconnectKey 变化 / resume) 续传。
      if (handle.lastEventId) lastIdRef.current = handle.lastEventId;
      handle.close();
      if (connection.current === handle) connection.current = null;
    };
  }, [enabled, paused, maxItems, reconnectKey]);

  // 卸载时确保 flush 掉残余缓冲, 不留悬挂定时器。
  useEffect(() => {
    return () => {
      connection.current?.close();
      if (flushTimer.current) clearInterval(flushTimer.current);
    };
  }, []);

  const pause = useCallback(() => {
    pausedRef.current = true;
    setPaused(true);
    setPhase("paused");
    flush();
    connection.current?.close();
    connection.current = null;
  }, [flush]);

  const resume = useCallback(() => {
    // 记住当前 id: 重连时服务端从该 id 之后回放, 暂停期间的日志不丢。
    const live = connection.current?.lastEventId;
    if (live) lastIdRef.current = live;
    pausedRef.current = false;
    setPaused(false);
    setPhase("connecting");
  }, []);

  const clear = useCallback(() => {
    buffer.current = [];
    setItems([]);
    statsRef.current = { totalReceived: 0, dropped: 0 };
    setStats(statsRef.current);
  }, []);

  // 事件里若带 id, 记录下来供 resume 使用 (由页面在 onEvent 外包装时写入)。
  const trackLastEventId = useCallback((id: string) => {
    if (id && id !== lastIdRef.current) {
      lastIdRef.current = id;
      setLastEventId(id);
    }
  }, []);

  return useMemo(
    () => ({
      items,
      // enabled=false 时对外恒为 idle (连接已在 effect 里关闭)。
      phase: enabled ? phase : ("idle" as SsePhase),
      paused,
      error,
      totalReceived: stats.totalReceived,
      dropped: stats.dropped,
      lastEventId,
      lastHeartbeatAt,
      pause,
      resume,
      clear,
      trackLastEventId,
    }),
    [enabled, items, phase, paused, error, stats, lastEventId, lastHeartbeatAt, pause, resume, clear, trackLastEventId],
  );
}
