import { useState, type FormEvent } from "react";

import { WEBHOOK_EVENT_CATALOG, WEBHOOK_EVENTS_WIRED } from "@/api/governance";
import type { WebhookSubscriptions } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { SelectField, TextField } from "@/components/Form";
import { JsonEditor } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { ConfirmDialog, Modal } from "@/components/Tabs";
import { useWebhooks } from "@/hooks/queries";
import { useSubscribeWebhook, useTriggerAutomation, useUnsubscribeWebhook } from "@/hooks/mutations";
import { urlHasSecrets } from "@/lib/redact";
import { redactUrl } from "@/lib/redact";
import { prettyJson } from "@/lib/format";

interface Row {
  event: string;
  url: string;
  wired: boolean;
}

function toRows(subscriptions: WebhookSubscriptions): Row[] {
  return Object.entries(subscriptions)
    .flatMap(([event, urls]) => (urls ?? []).map((url) => ({ event, url, wired: WEBHOOK_EVENTS_WIRED.has(event) })))
    .sort((a, b) => (a.event === b.event ? a.url.localeCompare(b.url) : a.event.localeCompare(b.event)));
}

/**
 * Webhook 订阅管理 (R2-③)。
 *
 * 两个必须讲清的后端现状 (SPEC_EXTRACTS 差异表):
 * 1. **HMAC 签名未实现** —— 投递请求不带签名头, 接收方无法验证来源真实性;
 *    推荐把密钥放进 URL query (投递用原值, 界面按后端同语义脱敏回显)。
 * 2. **目录里多数事件无生产者** —— 仅 message.responded / message.sent 已接线,
 *    订阅其余事件不会收到任何投递, UI 用"未接线"徽标明示, 不让用户误判为故障。
 */
export function WebhookManager() {
  const query = useWebhooks();
  const subscribe = useSubscribeWebhook();
  const unsubscribe = useUnsubscribeWebhook();
  const trigger = useTriggerAutomation();

  const [event, setEvent] = useState<string>(WEBHOOK_EVENT_CATALOG[0]);
  const [customEvent, setCustomEvent] = useState("");
  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState("");
  const [pendingRemove, setPendingRemove] = useState<Row | null>(null);
  const [triggerOpen, setTriggerOpen] = useState(false);
  const [triggerEvent, setTriggerEvent] = useState<string>(WEBHOOK_EVENT_CATALOG[0]);
  const [triggerData, setTriggerData] = useState("{}");
  const [triggerDataError, setTriggerDataError] = useState("");

  const effectiveEvent = event === "__custom__" ? customEvent.trim() : event;

  const onSubmit = (formEvent: FormEvent) => {
    formEvent.preventDefault();
    const target = url.trim();
    // SSRF 前置校验与后端同口径: 必须绝对 URL (后端还会拒绝内网地址, 失败原因原样回显)。
    if (!effectiveEvent) return;
    if (!target) {
      setUrlError("请填写回调 URL");
      return;
    }
    try {
      const parsed = new URL(target);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        setUrlError("仅支持 http/https");
        return;
      }
    } catch {
      setUrlError("不是合法的绝对 URL");
      return;
    }
    setUrlError("");
    subscribe.mutate(
      { event: effectiveEvent, url: target },
      { onSuccess: () => setUrl("") },
    );
  };

  const onTrigger = () => {
    let data: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(triggerData || "{}");
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setTriggerDataError("data 必须是 JSON 对象");
        return;
      }
      data = parsed as Record<string, unknown>;
    } catch (error) {
      setTriggerDataError(error instanceof Error ? error.message : "JSON 解析失败");
      return;
    }
    setTriggerDataError("");
    trigger.mutate({ event: triggerEvent, data }, { onSuccess: () => setTriggerOpen(false) });
  };

  const columns: Array<Column<Row>> = [
    { key: "event", header: "事件", render: (row) => <code className="code-inline">{row.event}</code> },
    {
      key: "wired",
      header: "生产者",
      render: (row) =>
        row.wired ? (
          <Badge tone="success">已接线</Badge>
        ) : (
          <Badge tone="warning" title="目录预留事件, 当前没有生产者, 订阅后不会收到投递">
            未接线
          </Badge>
        ),
    },
    {
      key: "url",
      header: "回调 URL",
      render: (row) => (
        <span className="mono small" title="界面按后端同语义脱敏 (userinfo 与 query 已掩码), 投递使用原值">
          {redactUrl(row.url)}
          {urlHasSecrets(row.url) ? <span className="muted"> (已脱敏)</span> : null}
        </span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      align: "right",
      render: (row) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPendingRemove(row)}
          data-testid={`webhook-remove-${row.event}`}
        >
          取消订阅
        </Button>
      ),
    },
  ];

  return (
    <div className="stack">
      <Callout tone="warning" title="安全现状: 投递未签名 (HMAC 未实现)">
        <span className="small">
          后端 Webhook 投递<strong>不带签名头</strong>, 接收方无法验证请求真实性。缓解办法:
          把共享密钥放进 URL query (如 <code className="code-inline">?token=…</code>) ——
          投递时使用原值, 界面与审计按后端同语义脱敏; 同时后端会对回调地址做 SSRF 防护
          (拒绝内网/环回地址), 失败原因会原样回显在下方提示里。
        </span>
      </Callout>

      <form className="row row--wrap" onSubmit={onSubmit} data-testid="webhook-subscribe-form" aria-label="新增 Webhook 订阅">
        <div style={{ minWidth: "14rem", flex: "1 1 14rem" }}>
          <SelectField
            label="事件"
            value={event}
            onChange={(changeEvent) => setEvent(changeEvent.target.value)}
            options={[
              ...WEBHOOK_EVENT_CATALOG.map((name) => ({
                value: name,
                label: WEBHOOK_EVENTS_WIRED.has(name) ? `${name} (已接线)` : `${name} (目录预留)`,
              })),
              { value: "__custom__", label: "自定义事件名…" },
            ]}
          />
        </div>
        {event === "__custom__" ? (
          <div style={{ minWidth: "12rem", flex: "1 1 12rem" }}>
            <TextField
              label="自定义事件名"
              value={customEvent}
              onChange={(changeEvent) => setCustomEvent(changeEvent.target.value)}
              placeholder="my.event"
            />
          </div>
        ) : null}
        <div style={{ minWidth: "20rem", flex: "2 1 20rem" }}>
          <TextField
            label="回调 URL"
            value={url}
            onChange={(changeEvent) => setUrl(changeEvent.target.value)}
            error={urlError}
            placeholder="https://example.com/hook?token=…"
            mono
            data-testid="webhook-url"
          />
        </div>
        <div style={{ alignSelf: "flex-end" }}>
          <Button type="submit" variant="primary" loading={subscribe.isPending} data-testid="webhook-subscribe">
            订阅
          </Button>
        </div>
      </form>

      <QueryState<WebhookSubscriptions>
        query={query}
        isEmpty={(subscriptions) => toRows(subscriptions).length === 0}
        empty={<span>还没有任何 Webhook 订阅。</span>}
      >
        {(subscriptions) => {
          const rows = toRows(subscriptions);
          return (
            <div className="stack stack--tight">
              <div className="row row--between">
                <span className="small muted">
                  {rows.length} 条订阅 · {Object.keys(subscriptions).length} 个事件
                </span>
                <Button variant="secondary" size="sm" onClick={() => setTriggerOpen(true)} data-testid="webhook-trigger-open">
                  手动触发一次
                </Button>
              </div>
              <Table
                columns={columns}
                rows={rows}
                rowKey={(row) => `${row.event}|${row.url}`}
                ariaLabel="Webhook 订阅"
                compact
                responsive
              />
            </div>
          );
        }}
      </QueryState>

      <ConfirmDialog
        open={pendingRemove !== null}
        title="取消订阅"
        impact={
          <span>
            将停止向 <span className="mono">{pendingRemove ? redactUrl(pendingRemove.url) : ""}</span> 投递{" "}
            <code className="code-inline">{pendingRemove?.event ?? ""}</code> 事件。
            外部集成会立即收不到推送, 且无法撤销 (需重新订阅)。
          </span>
        }
        confirmLabel="取消订阅"
        tone="danger"
        loading={unsubscribe.isPending}
        onConfirm={() => {
          if (!pendingRemove) return;
          unsubscribe.mutate(
            { event: pendingRemove.event, url: pendingRemove.url },
            { onSettled: () => setPendingRemove(null) },
          );
        }}
        onCancel={() => setPendingRemove(null)}
      />

      <Modal
        open={triggerOpen}
        title="手动触发事件"
        description="向该事件的全部订阅者投递一次 (POST JSON), 返回每个目标的投递结果。"
        onClose={() => setTriggerOpen(false)}
        footer={
          <div className="row row--end">
            <Button variant="ghost" onClick={() => setTriggerOpen(false)}>
              关闭
            </Button>
            <Button variant="primary" loading={trigger.isPending} onClick={onTrigger} data-testid="webhook-trigger-submit">
              触发
            </Button>
          </div>
        }
      >
        <div className="stack">
          <SelectField
            label="事件"
            value={triggerEvent}
            onChange={(changeEvent) => setTriggerEvent(changeEvent.target.value)}
            options={WEBHOOK_EVENT_CATALOG.map((name) => ({
              value: name,
              label: WEBHOOK_EVENTS_WIRED.has(name) ? `${name} (已接线)` : `${name} (目录预留)`,
            }))}
          />
          <JsonEditor
            label="data (JSON 对象)"
            value={triggerData}
            onChange={setTriggerData}
            onError={(message) => setTriggerDataError(message ?? "")}
            rows={6}
          />
          {triggerDataError ? <Callout tone="danger">{triggerDataError}</Callout> : null}
          {trigger.data ? (
            <Callout tone="success" title={`已触发 ${trigger.data.event}`}>
              <pre className="code-block">{prettyJson(trigger.data.delivered)}</pre>
            </Callout>
          ) : null}
          <p className="xs muted">
            未接线事件也可手动触发 —— 这正好用来验证回调地址可达性与 SSRF 拦截结果。
          </p>
        </div>
      </Modal>
    </div>
  );
}
