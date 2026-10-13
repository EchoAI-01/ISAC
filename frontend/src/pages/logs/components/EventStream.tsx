import { useCallback, useState } from "react";

import { EVENT_CATALOG, PUBLIC_EVENT_TYPES, streamEvents } from "@/api/events";
import type { StreamEvent } from "@/api/events";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { CodeBlock } from "@/components/DataDisplay";
import { TextField } from "@/components/Form";
import { useSse, type SsePhase } from "@/hooks/useSse";
import { cn } from "@/lib/cn";
import { formatClockTime, prettyJson } from "@/lib/format";

const PHASE_LABEL: Record<SsePhase, string> = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  paused: "已暂停",
  retrying: "重连中",
  closed: "已断开",
  error: "连接异常",
};

/**
 * 事件流页面 (F3 验收: `/events/stream` 页面化)。
 *
 * 必须把后端现状讲清楚 (SPEC §8.3 状态注): 桥接 EventBus 全部事件, 未登记
 * `event_type` 的落 `unknown` 且**仅 `"*"` 通配 scope 可见** (fail-closed) ——
 * 窄 scope token 看到空流是预期行为, 不是系统静默。v1 内置 WebUI 没有这层说明,
 * 用户只能猜。
 */
export function EventStream({ active }: { active: boolean }) {
  const [nameFilter, setNameFilter] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);

  const create = useCallback(
    (handlers: {
      onEvent: (event: StreamEvent) => void;
      onOpen?: () => void;
      onError?: (error: unknown, willRetry: boolean) => void;
      onClose?: () => void;
      onHeartbeat?: () => void;
      lastEventId?: string;
    }) =>
      streamEvents({
        lastEventId: handlers.lastEventId,
        onEvent: handlers.onEvent,
        onOpen: handlers.onOpen,
        onError: handlers.onError,
        onClose: handlers.onClose,
        onHeartbeat: handlers.onHeartbeat,
      }),
    [],
  );

  const sse = useSse<StreamEvent>({ create, enabled: active, maxItems: 1000 });
  const filter = nameFilter.trim().toLowerCase();
  const visible = filter ? sse.items.filter((item) => item.name.toLowerCase().includes(filter)) : sse.items;
  const rows = visible.slice().reverse();
  const unknownCount = sse.items.filter((item) => item.name === "unknown").length;

  return (
    <div className="stack">
      <Callout tone="info" title="为什么可能是空的 (后端实现现状)">
        <div className="stack stack--tight small">
          <div>
            SSE 桥接 EventBus <strong>全部</strong>事件, 事件名取 payload 的{" "}
            <code className="code-inline">event_type</code>; 未登记该字段的事件落{" "}
            <code className="code-inline">unknown</code> 兜底名, 且<strong>仅 `"*"` 通配 scope 可见</strong>{" "}
            (fail-closed, 防聊天原文与密钥被窄 scope token 读走)。
          </div>
          <div>
            §8.3 目录事件 (
            {EVENT_CATALOG.map((name, index) => (
              <span key={name}>
                <code className="code-inline">{name}</code>
                {index < EVENT_CATALOG.length - 1 ? "、" : ""}
              </span>
            ))}
            ) 多数<strong>尚无生产者</strong>; 当前仅 Webhook 侧{" "}
            <code className="code-inline">message.responded</code> /{" "}
            <code className="code-inline">message.sent</code> 已接线。公开事件仅{" "}
            {[...PUBLIC_EVENT_TYPES].map((name) => (
              <code className="code-inline" key={name}>
                {name}
              </code>
            ))}
            。
          </div>
          <div>
            所以: 窄 scope token 看到空流是预期行为, 不是故障。需要全量事件请用带{" "}
            <code className="code-inline">"*"</code> scope 的 token 登录。
          </div>
        </div>
      </Callout>

      <div className="row row--between">
        <div className="row row--tight">
          <Badge tone={sse.phase === "open" ? "success" : sse.phase === "error" ? "danger" : "warning"} dot>
            {PHASE_LABEL[sse.phase]}
          </Badge>
          <span className="small muted">
            已收 {sse.totalReceived} 条 · 显示 {rows.length}
            {unknownCount > 0 ? ` · 其中 unknown ${unknownCount} 条` : ""}
            {sse.dropped > 0 ? ` · 丢弃 ${sse.dropped} 条` : ""}
          </span>
        </div>
        <div className="row row--tight">
          <div style={{ minWidth: "14rem" }}>
            <TextField
              label="事件名过滤"
              value={nameFilter}
              onChange={(event) => setNameFilter(event.target.value)}
              placeholder="如 agent / unknown"
              data-testid="events-filter"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => (sse.paused ? sse.resume() : sse.pause())}
            data-testid="events-pause-toggle"
          >
            {sse.paused ? "继续" : "暂停"}
          </Button>
          <Button variant="ghost" size="sm" onClick={sse.clear}>
            清空
          </Button>
        </div>
      </div>

      {sse.error ? <Callout tone="danger" title="事件流异常">{sse.error}</Callout> : null}

      <div className="console" data-testid="events-console" tabIndex={0} role="log" aria-label="实时事件流">
        {rows.length === 0 ? (
          <div className="muted">
            {sse.phase === "connecting" ? "正在连接 /api/v1/events/stream …" : "暂无事件 (见上方说明)。"}
          </div>
        ) : (
          rows.map((item) => {
            const key = item.id || `${item.receivedAt}-${item.name}`;
            const isOpen = openId === key;
            return (
              <div key={key} className={cn("console__line", item.name === "unknown" && "console__line--warning")}>
                <span className="console__ts">{formatClockTime(item.receivedAt)}</span>
                <span className="console__level">{item.name}</span>
                <span>
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    style={{ padding: 0, minHeight: "auto" }}
                    aria-expanded={isOpen}
                    aria-label={`展开事件 ${item.name} 的 payload`}
                    onClick={() => setOpenId(isOpen ? null : key)}
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>{" "}
                  <span className="muted">id={item.id || "—"}</span>
                  {isOpen ? (
                    <span style={{ display: "block" }}>
                      <CodeBlock ariaLabel={`事件 ${item.name} 的 payload`} maxHeight="16rem">
                        {prettyJson(item.payload)}
                      </CodeBlock>
                    </span>
                  ) : (
                    <span className="truncate"> {summarize(item.payload)}</span>
                  )}
                </span>
              </div>
            );
          })
        )}
      </div>

      <p className="xs muted">
        断线恢复: 重连自动带 <code className="code-inline">Last-Event-ID</code>, 服务端从该 id 之后回放
        (缓冲上限 1000 条)。连接数上限 100, 超限返回 429。
      </p>
    </div>
  );
}

/** payload 的一行摘要 (只取几个常见键, 避免整段 JSON 挤爆行)。 */
function summarize(payload: unknown): string {
  if (typeof payload === "string") return payload.slice(0, 120);
  if (!payload || typeof payload !== "object") return String(payload ?? "");
  const record = payload as Record<string, unknown>;
  const parts: string[] = [];
  for (const key of ["agent_id", "session_id", "platform", "task_id", "provider", "action", "status"]) {
    const value = record[key];
    if (value !== undefined && value !== null && value !== "") parts.push(`${key}=${String(value)}`);
    if (parts.length >= 3) break;
  }
  return parts.join(" · ");
}
