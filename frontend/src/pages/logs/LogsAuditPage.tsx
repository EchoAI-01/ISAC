import { Callout, PageHeader } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { useUrlEnum, useUrlTab } from "@/hooks/useUrlState";
import type { LogLevel } from "@/api/types";
import { LOG_LEVELS } from "@/api/system";

import { AuditExplorer } from "./components/AuditExplorer";
import { EventStream } from "./components/EventStream";
import { LogConsole } from "./components/LogConsole";
import { WebhookManager } from "./components/WebhookManager";

const TABS = ["logs", "events", "audit", "webhooks"] as const;
const LEVEL_VALUES = ["", ...LOG_LEVELS] as const;
type LevelParam = (typeof LEVEL_VALUES)[number];

/**
 * Logs & Audit 域 (§8.1 IA 第 9 行)。
 *
 * F3 验收落点: 实时日志台 (`/logs/tail` SSE) + 事件流页面化 (`/events/stream`)。
 * 两个 SSE 页面都受 `active` 控制 —— 离开该 tab 立即断开, 不占服务端连接名额
 * (日志台默认 50、事件流默认 100, 超限 429)。
 */
export default function LogsAuditPage() {
  const [tab, setTab] = useUrlTab(TABS, "logs");
  const [level, setLevel] = useUrlEnum<LevelParam>("level", LEVEL_VALUES, "");

  return (
    <div className="stack">
      <PageHeader
        title="日志与审计"
        description="实时结构化日志、事件流、控制面审计、Webhook 订阅与投递结果"
      />

      <Tabs
        ariaLabel="日志与审计分区"
        value={tab}
        onChange={setTab}
        items={[
          {
            value: "logs",
            label: "实时日志",
            content: (
              <LogConsole
                active={tab === "logs"}
                level={level as LogLevel | ""}
                onLevelChange={(next) => setLevel((next || "") as LevelParam)}
              />
            ),
          },
          {
            value: "events",
            label: "事件流",
            content: <EventStream active={tab === "events"} />,
          },
          {
            value: "audit",
            label: "审计",
            content: tab === "audit" ? <AuditExplorer /> : null,
          },
          {
            value: "webhooks",
            label: "Webhook",
            content: tab === "webhooks" ? <WebhookManager /> : null,
          },
        ]}
      />

      <Callout tone="info" title="SSE 为什么用 fetch 而不是 EventSource">
        <span className="small">
          浏览器原生 <code className="code-inline">EventSource</code> 不支持自定义请求头, 因此在
          Bearer 轨 (部署禁用 session 认证时) 无法鉴权。本控制台用 fetch 流式读取,
          两条认证轨都能用; 断线重连自动带{" "}
          <code className="code-inline">Last-Event-ID</code>, 由服务端回放断线期间的缓冲。
        </span>
      </Callout>
    </div>
  );
}
