import { Badge, statusTone } from "@/components/Badge";
import { ShortId } from "@/components/DataDisplay";
import { Pagination } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { Callout } from "@/components/Card";
import { Table, type Column } from "@/components/Table";
import type { UsageEventRow } from "@/api/types";
import { useUsageEvents } from "@/hooks/queries";
import { useUrlNumber } from "@/hooks/useUrlState";
import { formatTimestamp, formatTokens } from "@/lib/format";

import { CostCell } from "./UsageSummaryTab";
import { useUsageUrlState } from "../useUsageUrlState";

const PAGE_SIZES = [20, 50, 100, 200];

/**
 * 明细 tab: GET /usage/models/events (需要 usage:detail scope, 403 由 QueryState 呈现)。
 *
 * 每行是一次**物理请求** (含重试与回退); fallback_from 非空表示该行是回退调用,
 * 用醒目 Badge 标出来源模型。pricing_version 保留价格快照版本, 成本可追溯。
 * 分页 limit/offset 写 URL。
 */
export default function UsageEventsTab() {
  const state = useUsageUrlState();
  const [limit, setLimit] = useUrlNumber("limit", 50);
  const [offset, setOffset] = useUrlNumber("offset", 0);

  const events = useUsageEvents({ ...state.filter, limit, offset });

  const columns: Array<Column<UsageEventRow>> = [
    { key: "created", header: "时间", label: "时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
    { key: "agent", header: "agent", label: "agent_id", render: (row) => <span className="mono small">{row.agent_id || "—"}</span> },
    { key: "session", header: "session", label: "session_id", render: (row) => (row.session_id ? <ShortId value={row.session_id} /> : "—") },
    { key: "provider", header: "provider", label: "provider", render: (row) => <code className="code-inline">{row.provider || "—"}</code> },
    { key: "model", header: "model", label: "model", render: (row) => <span className="mono small">{row.model || "—"}</span> },
    { key: "modality", header: "modality", label: "modality", render: (row) => row.modality || "—" },
    { key: "operation", header: "operation", label: "operation", render: (row) => row.operation || "—" },
    {
      key: "tokens",
      header: "tokens (p/c/总)",
      label: "tokens prompt completion total",
      align: "right",
      render: (row) => (
        <span className="tabular small">
          {row.prompt_tokens === null ? "—" : formatTokens(row.prompt_tokens)}/
          {row.completion_tokens === null ? "—" : formatTokens(row.completion_tokens)}/
          <strong>{row.total_tokens === null ? "—" : formatTokens(row.total_tokens)}</strong>
        </span>
      ),
    },
    {
      key: "latency",
      header: "latency_ms",
      label: "latency_ms",
      align: "right",
      render: (row) => <span className="tabular">{row.latency_ms ?? "—"}</span>,
    },
    {
      key: "status",
      header: "status",
      label: "status",
      render: (row) => (row.status ? <Badge tone={statusTone(row.status)}>{row.status}</Badge> : "—"),
    },
    {
      key: "fallback",
      header: "回退来源",
      label: "回退来源",
      render: (row) =>
        row.fallback_from ? (
          <Badge tone="danger" title={`该请求是回退调用: 原模型 ${row.fallback_from} 失败后回退到 ${row.model ?? "当前模型"}`}>
            ⤺ 回退自 {row.fallback_from}
          </Badge>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: "cost", header: "估算成本", label: "估算成本 USD", align: "right", render: (row) => <CostCell value={row.estimated_cost} /> },
    {
      key: "pricing",
      header: "pricing_version",
      label: "pricing_version",
      render: (row) => (row.pricing_version ? <code className="code-inline" title="成本按该价格快照计算, 可追溯">{row.pricing_version}</code> : "—"),
    },
  ];

  return (
    <div className="stack" data-testid="usage-events">
      <Callout tone="info" title="明细口径">
        <span className="small">
          每行是一次物理模型请求 (<code className="code-inline">usage:detail</code> scope),
          含重试与回退 —— 同一逻辑回复可能对应多行。回退行以红色 Badge 标出来源模型;
          成本为按 <code className="code-inline">pricing_version</code> 快照查表的估算值 (USD), 价格未知显示 —。
        </span>
      </Callout>

      <QueryState
        query={events}
        isEmpty={(data) => data.length === 0}
        empty={<p className="small muted">该范围与筛选下没有明细记录, 或计量未启用 (observability.usage.enabled = true)。</p>}
      >
        {(data) => (
          <div className="stack">
            <div data-testid="usage-events-table">
              <Table
                ariaLabel="用量明细 (物理请求)"
                compact
                responsive
                columns={columns}
                rows={data}
                rowKey={(row, index) => `${row.event_id || index}`}
              />
            </div>
            <Pagination
              ariaLabel="用量明细分页"
              offset={offset}
              limit={limit}
              hasMore={data.length === limit}
              pageSizeOptions={PAGE_SIZES}
              onChange={setOffset}
              onPageSizeChange={(size) => {
                setLimit(size);
                setOffset(0);
              }}
            />
          </div>
        )}
      </QueryState>
    </div>
  );
}
