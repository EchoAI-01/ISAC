import { Link } from "react-router-dom";

import { parseCost } from "@/api/usage";
import { Badge, statusTone } from "@/components/Badge";
import { Card, PageHeader } from "@/components/Card";
import { BarChart, Stat, StatGrid } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { UnavailableState } from "@/components/StateViews";
import { Table, type Column } from "@/components/Table";
import { SegmentedControl } from "@/components/Inputs";
import { useAudit, useAgents, useApprovals, useHealth, useMetricsSnapshot, useSessions, useUsageSummary } from "@/hooks/queries";
import { useUrlEnum } from "@/hooks/useUrlState";
import { formatCost, formatInt, formatRelative, formatTimestamp, formatTokens } from "@/lib/format";
import { useNowSeconds } from "@/lib/time";
import type { AuditEntry, UsageSummaryRow } from "@/api/types";

type TimeRange = "1h" | "24h" | "7d" | "30d";

const RANGE_SECONDS: Record<TimeRange, number> = {
  "1h": 3600,
  "24h": 86400,
  "7d": 7 * 86400,
  "30d": 30 * 86400,
};

const RANGE_OPTIONS = Object.keys(RANGE_SECONDS) as TimeRange[];

/** 汇总多行用量 → 单行合计 (成本按字符串转数字后相加, 全未知则 null)。 */
function totalize(rows: UsageSummaryRow[]): { tokens: number; requests: number; cost: number | null } {
  let tokens = 0;
  let requests = 0;
  let cost: number | null = null;
  for (const row of rows) {
    tokens += row.total_tokens ?? 0;
    requests += row.request_count ?? 0;
    const parsed = parseCost(row.estimated_cost_sum);
    if (parsed !== null) cost = (cost ?? 0) + parsed;
  }
  return { tokens, requests, cost };
}

/**
 * Dashboard (十域之一, CONTROL_PLANE_SPEC §8.1)。
 *
 * 数据来源全部真实端点, 无占位数字:
 * - /health (Agent/Channel/LLM/控制面聚合)
 * - /api/v1/metrics (消息计数器)
 * - /api/v1/sessions、/api/v1/agents
 * - /api/v1/usage/models/summary (计量未启用 → unavailable 说明, 不显示 0)
 * - /api/v1/audit、/api/v1/approvals (窄 scope → permission-denied 说明)
 */
export default function DashboardPage() {
  const [range, setRange] = useUrlEnum<TimeRange>("range", RANGE_OPTIONS, "24h");
  const nowSeconds = useNowSeconds();
  const from = nowSeconds - RANGE_SECONDS[range];

  const health = useHealth();
  const metrics = useMetricsSnapshot();
  const agents = useAgents();
  const sessions = useSessions();
  const usage = useUsageSummary({ from, to: nowSeconds, group_by: "provider" });
  const audit = useAudit({ limit: 10 });
  const approvals = useApprovals();

  const auditColumns: Array<Column<AuditEntry>> = [
    {
      key: "time",
      header: "时间",
      label: "时间",
      render: (row) => (
        <span className="nowrap tabular" title={formatTimestamp(row.timestamp)}>
          {formatRelative(row.timestamp, nowSeconds)}
        </span>
      ),
    },
    { key: "actor", header: "操作者", label: "操作者", render: (row) => <span className="mono">{row.actor || "—"}</span> },
    { key: "action", header: "动作", label: "动作", render: (row) => <code className="code-inline">{row.action}</code> },
    { key: "target", header: "目标", label: "目标", render: (row) => row.target || "—" },
    {
      key: "status",
      header: "结果",
      label: "结果",
      render: (row) => <Badge tone={row.status_code < 400 ? "success" : "danger"}>{row.status_code}</Badge>,
    },
  ];

  return (
    <div className="stack stack--loose">
      <PageHeader
        title="Dashboard"
        description="Agent / Channel / Provider 健康、消息与任务、Token 与成本、错误与告警趋势"
        actions={
          <div className="row row--tight">
            <span className="toolbar__label" id="dashboard-range-label">
              时间范围
            </span>
            <SegmentedControl
              ariaLabel="用量时间范围"
              options={RANGE_OPTIONS.map((value) => ({ value, label: value }))}
              value={range}
              onChange={setRange}
            />
          </div>
        }
      />

      {/* ── 概览统计 ─────────────────────────────── */}
      <StatGrid>
        <Stat
          label="Agent"
          value={
            health.data ? `${health.data.subsystems.agents.running} / ${health.data.subsystems.agents.total}` : "—"
          }
          meta="运行中 / 总数"
          tone={health.data && health.data.subsystems.agents.running > 0 ? "success" : "warning"}
          testId="stat-agents"
        />
        <Stat
          label="后端健康"
          value={health.data ? health.data.status : "—"}
          meta={health.data ? `LLM: ${health.data.subsystems.llm}` : "探测中"}
          tone={health.data?.status === "ok" ? "success" : "warning"}
          testId="stat-health"
        />
        <Stat
          label="Channel"
          value={health.data ? health.data.subsystems.channels.length : "—"}
          meta={health.data?.subsystems.channels.join(", ") || "未注册任何平台"}
          testId="stat-channels"
        />
        <Stat
          label="活跃会话"
          value={sessions.data ? sessions.data.sessions.length : "—"}
          meta={sessions.isError ? "不可读 (权限或子系统未启用)" : "SessionManager 在册"}
          testId="stat-sessions"
        />
        <Stat
          label="消息 (累计)"
          value={
            metrics.data
              ? formatInt(metrics.data.counters["isac_messages_processed_total"] ?? 0)
              : "—"
          }
          meta={
            metrics.data
              ? `接收 ${formatInt(metrics.data.counters["isac_messages_received_total"] ?? 0)} · 失败 ${formatInt(
                  metrics.data.counters["isac_messages_failed_total"] ?? 0,
                )} · 丢弃 ${formatInt(metrics.data.counters["isac_messages_dropped_total"] ?? 0)}`
              : "指标未就绪"
          }
          tone={
            metrics.data && (metrics.data.counters["isac_messages_failed_total"] ?? 0) > 0 ? "danger" : "default"
          }
          testId="stat-messages"
        />
        <Stat
          label="待审批"
          value={approvals.data ? approvals.data.approvals.length : "—"}
          meta={
            approvals.data
              ? approvals.data.approvals.length > 0
                ? "ask 档高危工具等待裁决"
                : "无 ask 档工具等待裁决"
              : "审批门未接线或无权限"
          }
          tone={approvals.data && approvals.data.approvals.length > 0 ? "warning" : "default"}
          testId="stat-approvals"
        />
      </StatGrid>

      {/* ── Token 与成本 ─────────────────────────── */}
      <Card
        title={`Token 与成本 (近 ${range})`}
        subtitle="估算成本来自 pricing 快照查表; 组内价格全未知时显示 —, 不伪造成 0 (SPEC §九 Cost)"
      >
        <QueryState
          query={usage}
          isEmpty={(rows) => rows.length === 0}
          empty={
            <UnavailableState
              title="该时间范围内无用量记录"
              description="可能原因: 期间没有模型调用, 或计量未启用。"
              configHint="observability.usage.enabled = true"
            />
          }
        >
          {(rows) => {
            const total = totalize(rows);
            return (
              <div className="stack">
                <StatGrid>
                  <Stat label="请求数" value={formatInt(total.requests)} meta="物理请求 (含重试与回退)" />
                  <Stat label="Token" value={formatTokens(total.tokens)} meta="prompt + completion + 明细列合计" />
                  <Stat
                    label="估算成本"
                    value={formatCost(total.cost)}
                    meta={total.cost === null ? "价格未知 (未命中价目表)" : "USD · 估算值"}
                    tone={total.cost === null ? "warning" : "default"}
                  />
                </StatGrid>
                <BarChart
                  ariaLabel={`近 ${range} 各 Provider 的 Token 用量`}
                  rows={rows.map((row) => ({
                    label: String(row.provider ?? "unknown"),
                    value: row.total_tokens ?? 0,
                    display: `${formatTokens(row.total_tokens ?? 0)} · ${formatCost(parseCost(row.estimated_cost_sum))}`,
                  }))}
                />
              </div>
            );
          }}
        </QueryState>
      </Card>

      {/* ── 子系统健康 ───────────────────────────── */}
      <div className="row" style={{ alignItems: "stretch" }}>
        <Card title="Agent 状态" className="grow" actions={<Link className="btn btn--secondary btn--sm" to="/agents">管理</Link>}>
          <QueryState query={agents} isEmpty={(rows) => rows.length === 0} empty={<p className="small muted">尚未创建任何 Agent。</p>}>
            {(rows) => (
              <Table
                ariaLabel="Agent 状态"
                compact
                columns={[
                  {
                    key: "agent_id",
                    header: "agent_id",
                    label: "agent_id",
                    render: (row) => <Link to={`/agents/${row.agent_id}`} className="mono">{row.agent_id}</Link>,
                  },
                  {
                    key: "status",
                    header: "状态",
                    label: "状态",
                    render: (row) => <Badge tone={statusTone(row.status)} dot>{row.status}</Badge>,
                  },
                ]}
                rows={rows}
                rowKey={(row) => row.agent_id}
              />
            )}
          </QueryState>
        </Card>

        <Card title="近期审计" className="grow" actions={<Link className="btn btn--secondary btn--sm" to="/logs?tab=audit">全部</Link>}>
          <QueryState
            query={audit}
            isEmpty={(rows) => rows.length === 0}
            empty={<p className="small muted">暂无审计记录 (写操作才会产生审计事件)。</p>}
          >
            {(rows) => (
              <Table
                ariaLabel="近期审计事件"
                compact
                columns={auditColumns}
                rows={rows}
                rowKey={(row, index) => `${row.timestamp}-${row.action}-${index}`}
              />
            )}
          </QueryState>
        </Card>
      </div>
    </div>
  );
}
