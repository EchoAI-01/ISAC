/** SSE 客户端 (fetch 流式实现, 不用 EventSource)。
 *
 * 为什么不用 EventSource (F3):
 * 1. EventSource 无法携带自定义请求头 —— Bearer 轨 (后端未启用会话 Cookie 的部署,
 *    例如纯 setup 密码模式) 下 `/logs/tail`、`/events/stream` 会 401, v1 内置 WebUI
 *    因此直接禁用实时能力;
 * 2. 需要主动控制重连节奏与行数上限 (SPEC §8.3: 日志按需订阅并设置速率和行数上限);
 * 3. 两条 SSE 通道 (日志 / 事件) 共用一套解析、断线恢复与背压逻辑。
 *
 * 断线恢复 (SPEC §8.3): 重连时带 `Last-Event-ID` 请求头, 服务端从该 id 之后回放
 * (routes_logs / routes_events 都支持 Header 优先 + query 回退)。
 */

import { apiUrl, authHeaders } from "./client";

export interface SseEvent {
  /** 服务端 `id:` 字段 (日志为 _seq, 事件为递增 seq); 缺省为空串。 */
  id: string;
  /** 服务端 `event:` 字段; 未给时为 "message"。 */
  event: string;
  /** `data:` 字段 (多行按 \n 连接), 原始字符串。 */
  data: string;
  /** 客户端接收时刻 (epoch 秒), 供展示与限速统计。 */
  receivedAt: number;
}

export interface SseOptions {
  /** 契约路径, 例如 `/api/v1/logs/tail`。 */
  path: string;
  /** query 参数 (undefined / 空串自动丢弃)。 */
  query?: Record<string, string | number | boolean | undefined>;
  onEvent: (event: SseEvent) => void;
  /** 连接建立 (HTTP 200 + content-type 校验通过)。 */
  onOpen?: () => void;
  /** 连接异常; willRetry=false 表示已放弃重连 (达上限或被 close)。 */
  onError?: (error: unknown, willRetry: boolean) => void;
  /** 流被服务端正常结束或客户端 close。 */
  onClose?: () => void;
  /** 心跳 (SSE 注释行) —— 用于"连接存活"指示。 */
  onHeartbeat?: () => void;
  /** 初始 Last-Event-ID (从上次断开处续传)。 */
  lastEventId?: string;
  /** 最大重连次数 (默认 8; 0 = 不重连)。 */
  maxRetries?: number;
  /** 重连基础间隔 ms (指数退避, 上限 15s; 默认 1000)。 */
  retryDelayMs?: number;
  /** 外部取消信号。 */
  signal?: AbortSignal;
}

export type SseState = "connecting" | "open" | "closed" | "retrying";

export interface SseConnection {
  close: () => void;
  readonly state: SseState;
  readonly lastEventId: string;
}

const MAX_RETRY_DELAY_MS = 15_000;

/** 解析一帧 SSE 文本 (可能含多行 data 与注释行)。 */
export function parseSseFrame(frame: string): SseEvent | "heartbeat" | null {
  const lines = frame.split("\n");
  let id = "";
  let event = "";
  const dataLines: string[] = [];
  let sawComment = false;

  for (const rawLine of lines) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line === "") continue;
    if (line.startsWith(":")) {
      sawComment = true;
      continue;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "id":
        id = value;
        break;
      case "event":
        event = value;
        break;
      case "data":
        dataLines.push(value);
        break;
      default:
        // retry / 未知字段忽略 (SSE 规范允许)。
        break;
    }
  }

  if (dataLines.length === 0) return sawComment ? "heartbeat" : null;
  return {
    id,
    event: event || "message",
    data: dataLines.join("\n"),
    receivedAt: Date.now() / 1000,
  };
}

/** 建立 SSE 连接。返回句柄可 close; 内部自动重连并带 Last-Event-ID。 */
export function connectSse(options: SseOptions): SseConnection {
  const {
    path,
    query,
    onEvent,
    onOpen,
    onError,
    onClose,
    onHeartbeat,
    maxRetries = 8,
    retryDelayMs = 1000,
  } = options;

  let state: SseState = "connecting";
  let lastEventId = options.lastEventId ?? "";
  let closed = false;
  let attempt = 0;
  let controller: AbortController | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const externalSignal = options.signal;
  if (externalSignal?.aborted) {
    const aborted: SseConnection = {
      close: () => undefined,
      get state() {
        return "closed" as const;
      },
      get lastEventId() {
        return lastEventId;
      },
    };
    return aborted;
  }

  function buildUrl(): string {
    const url = new URL(apiUrl(path), window.location.origin);
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value === undefined || value === "") continue;
      url.searchParams.set(key, String(value));
    }
    // query 回退 (服务端 Header 优先, 手动/测试场景可用 query)。
    if (lastEventId) url.searchParams.set("last_event_id", lastEventId);
    return url.toString();
  }

  async function run(): Promise<void> {
    if (closed) return;
    state = attempt === 0 ? "connecting" : "retrying";
    controller = new AbortController();
    const onExternalAbort = () => close();
    externalSignal?.addEventListener("abort", onExternalAbort, { once: true });

    try {
      const headers: Record<string, string> = {
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
        ...authHeaders("GET"),
      };
      if (lastEventId) headers["Last-Event-ID"] = lastEventId;

      const response = await fetch(buildUrl(), {
        method: "GET",
        headers,
        credentials: apiUrl(path).startsWith("http") ? "include" : "same-origin",
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new SseHttpError(response.status, `SSE 连接失败 (HTTP ${response.status})`);
      }
      if (!response.body) {
        throw new Error("SSE 响应无 body (环境不支持流式读取)");
      }

      attempt = 0;
      state = "open";
      onOpen?.();

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE 帧以空行分隔 (兼容 \r\n)。
        let boundary = findFrameBoundary(buffer);
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary.start);
          buffer = buffer.slice(boundary.end);
          handleFrame(frame);
          boundary = findFrameBoundary(buffer);
        }
      }
      // 流正常结束: 若未 close 则按断线处理并重连。
      if (!closed) throw new Error("SSE 流被服务端关闭");
    } catch (error) {
      if (closed || (error instanceof DOMException && error.name === "AbortError")) {
        finish();
        return;
      }
      const willRetry = attempt < maxRetries;
      state = willRetry ? "retrying" : "closed";
      onError?.(error, willRetry);
      if (!willRetry) {
        finish();
        return;
      }
      attempt += 1;
      const delay = Math.min(MAX_RETRY_DELAY_MS, retryDelayMs * 2 ** (attempt - 1));
      retryTimer = setTimeout(() => {
        retryTimer = null;
        void run();
      }, delay);
      return;
    } finally {
      externalSignal?.removeEventListener("abort", onExternalAbort);
    }

    if (closed) {
      finish();
    } else {
      // 正常读完但未 close (max_chunks 场景): 视为一次结束, 触发 onClose 不重连。
      state = "closed";
      onClose?.();
    }
  }

  function handleFrame(frame: string): void {
    const parsed = parseSseFrame(frame);
    if (parsed === null) return;
    if (parsed === "heartbeat") {
      onHeartbeat?.();
      return;
    }
    if (parsed.id) lastEventId = parsed.id;
    onEvent(parsed);
  }

  function finish(): void {
    state = "closed";
    onClose?.();
  }

  function close(): void {
    if (closed) return;
    closed = true;
    state = "closed";
    if (retryTimer !== null) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    controller?.abort();
    controller = null;
  }

  void run();

  return {
    close,
    get state() {
      return state;
    },
    get lastEventId() {
      return lastEventId;
    },
  };
}

/** SSE 非 200 响应 (便于调用方区分 401/429 与网络断开)。 */
export class SseHttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "SseHttpError";
    this.status = status;
  }
}

interface Boundary {
  start: number;
  end: number;
}

/** 找第一个帧边界 (空行), 返回帧内容区间与消耗掉的总长度。 */
function findFrameBoundary(buffer: string): Boundary | -1 {
  const lf = buffer.indexOf("\n\n");
  const crlf = buffer.indexOf("\r\n\r\n");
  if (lf === -1 && crlf === -1) return -1;
  if (crlf !== -1 && (lf === -1 || crlf < lf)) {
    return { start: crlf, end: crlf + 4 };
  }
  return { start: lf, end: lf + 2 };
}
