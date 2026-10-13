import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { LOG_LEVELS, tailLogs } from "@/api/system";
import type { LogEntry, LogLevel } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { SelectField } from "@/components/Form";
import { useSse, type SseHandlers, type SsePhase } from "@/hooks/useSse";
import { cn } from "@/lib/cn";
import { formatClockTime, prettyJson } from "@/lib/format";

/** 连接状态 → 徽标语调 + 文案 (非颜色冗余: 文本同时表达状态)。 */
const PHASE_META: Record<SsePhase, { tone: "neutral" | "success" | "warning" | "danger" | "info"; label: string }> = {
  idle: { tone: "neutral", label: "未连接" },
  connecting: { tone: "info", label: "连接中" },
  open: { tone: "success", label: "已连接" },
  paused: { tone: "warning", label: "已暂停" },
  retrying: { tone: "warning", label: "重连中" },
  closed: { tone: "neutral", label: "已断开" },
  error: { tone: "danger", label: "连接异常" },
};

const LEVEL_VALUES = ["", ...LOG_LEVELS] as const;

/** 展开的日志字段 (除渲染列之外的结构化 kv)。 */
function extraFields(entry: LogEntry): Array<[string, string]> {
  const skip = new Set(["_seq", "_ts", "level", "logger", "event", "timestamp"]);
  return Object.entries(entry)
    .filter(([key]) => !skip.has(key))
    .map(([key, value]) => [key, typeof value === "object" ? prettyJson(value) : String(value)] as [string, string]);
}

export interface LogConsoleProps {
  /** 服务端级别过滤 (routes_logs 的 ?level=), 空串 = 全部。 */
  level: LogLevel | "";
  onLevelChange: (level: LogLevel | "") => void;
  /** 是否活跃 (非当前 tab 时必须断开, 不占服务端连接名额)。 */
  active: boolean;
  maxItems?: number;
}

/**
 * 实时日志台 (F3 验收: `/logs/tail` SSE)。
 *
 * 工程要点:
 * - 用 fetch 流式 SSE 而非 EventSource, 因此 **Bearer 轨也能用** (v1 内置 WebUI
 *   在 Bearer 模式下直接禁用日志台);
 * - level 变化经 `reconnectKey` 重连并带 Last-Event-ID, 暂停期间的日志由服务端回放;
 * - 事件先进 ref 缓冲、按 150ms 批量刷 state (`useSse`), 高频日志不卡主线程;
 * - 行数上限 + dropped 计数明示, 不静默丢弃 (§8.3 速率与行数上限)。
 */
export function LogConsole({ level, onLevelChange, active, maxItems = 2000 }: LogConsoleProps) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const consoleRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const create = useCallback(
    (handlers: SseHandlers<LogEntry>) =>
      tailLogs({
        level,
        lastEventId: handlers.lastEventId,
        onEntry: handlers.onEvent,
        onOpen: handlers.onOpen,
        onError: handlers.onError,
        onClose: handlers.onClose,
        onHeartbeat: handlers.onHeartbeat,
      }),
    [level],
  );

  const sse = useSse<LogEntry>({ create, enabled: active, maxItems, reconnectKey: level });

  // 新日志到达时滚到底 (用户手动上滚时不打断: 由 autoScroll 开关控制)。
  useEffect(() => {
    if (!autoScroll) return;
    const node = consoleRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [sse.items.length, autoScroll]);

  const phase = PHASE_META[sse.phase];
  const rows = useMemo(() => sse.items.slice().reverse(), [sse.items]);

  const toggle = (seq: number) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  return (
    <div className="stack">
      <div className="row row--between">
        <div className="row row--tight">
          <Badge tone={phase.tone} dot>
            {phase.label}
          </Badge>
          <span className="small muted">
            已收 {sse.totalReceived} 条 · 显示 {sse.items.length}/{maxItems}
            {sse.dropped > 0 ? ` · 因行数上限丢弃 ${sse.dropped} 条` : ""}
          </span>
          {sse.lastHeartbeatAt ? (
            <span className="small muted">心跳 {formatClockTime(sse.lastHeartbeatAt)}</span>
          ) : null}
        </div>
        <div className="row row--tight">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => (sse.paused ? sse.resume() : sse.pause())}
            data-testid="logs-pause-toggle"
          >
            {sse.paused ? "继续 (服务端回放暂停期间日志)" : "暂停"}
          </Button>
          <Button variant="ghost" size="sm" onClick={sse.clear} data-testid="logs-clear">
            清空
          </Button>
        </div>
      </div>

      <div className="row">
        <div style={{ minWidth: "12rem" }}>
          <SelectField
            label="级别过滤 (服务端)"
            value={level}
            onChange={(event) => onLevelChange(event.target.value as LogLevel | "")}
            options={LEVEL_VALUES.map((value) => ({
              value,
              label: value === "" ? "全部级别" : `${value} 及以上`,
            }))}
            hint="改变级别会带 Last-Event-ID 重连, 不丢暂停/切换期间的日志"
          />
        </div>
        <label className="checkbox" style={{ alignSelf: "flex-end" }}>
          <input type="checkbox" checked={autoScroll} onChange={(event) => setAutoScroll(event.target.checked)} />
          <span>自动滚到最新</span>
        </label>
      </div>

      {sse.error ? (
        <Callout tone="danger" title="日志流异常">
          <div>{sse.error}</div>
          <div className="small" style={{ marginTop: "var(--space-2)" }}>
            常见原因: 401 凭据失效 (重新登录) · 403 需要 <code className="code-inline">"*"</code> 通配 scope
            (系统日志含聊天原文与堆栈, 属最敏感数据面) · 429 连接数达上限 (默认 50, 关掉其它日志台标签页)。
          </div>
        </Callout>
      ) : null}

      {!active ? null : (
        <div className="console" ref={consoleRef} data-testid="logs-console" tabIndex={0} role="log" aria-label="实时日志" aria-live="off">
          {rows.length === 0 ? (
            <div className="muted">
              {sse.phase === "connecting"
                ? "正在连接 /api/v1/logs/tail …"
                : "暂无日志。级别过滤为服务端过滤 (warning 及以上时 info/debug 不会推送)。"}
            </div>
          ) : (
            rows.map((entry) => {
              const seq = entry._seq;
              const levelName = String(entry.level ?? "info").toLowerCase();
              const extras = extraFields(entry);
              const isOpen = expanded.has(seq);
              return (
                <div key={seq} className={cn("console__line", `console__line--${levelName}`)}>
                  <span className="console__ts">{formatClockTime(entry._ts)}</span>
                  <span className="console__level">{levelName}</span>
                  <span>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      style={{ padding: 0, minHeight: "auto" }}
                      onClick={() => toggle(seq)}
                      aria-expanded={isOpen}
                      aria-label={`展开日志 #${seq} 的结构化字段`}
                    >
                      {isOpen ? "▾" : "▸"}
                    </button>{" "}
                    <strong>{String(entry.logger ?? "")}</strong> {String(entry.event ?? "")}
                    {isOpen && extras.length > 0 ? (
                      <span style={{ display: "block", paddingLeft: "1rem", opacity: 0.85 }}>
                        {extras.map(([key, value]) => (
                          <span key={key} style={{ display: "block" }}>
                            {key}={value}
                          </span>
                        ))}
                      </span>
                    ) : null}
                  </span>
                </div>
              );
            })
          )}
        </div>
      )}

      <p className="xs muted">
        帧格式 <code className="code-inline">id=&lt;_seq&gt; event=log data=&lt;json&gt;</code>;
        心跳为 SSE 注释行, 只用于保活与"连接存活"指示。
      </p>
    </div>
  );
}
