import { useState } from "react";

import type { ApprovalDecisionRecord, ApprovalRequest } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { CodeBlock, ShortId } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useDecideApproval } from "@/hooks/mutations";
import { useApprovalHistory, useApprovals } from "@/hooks/queries";
import { formatDuration, formatTimestamp, truncate } from "@/lib/format";
import { prettyJson } from "@/lib/format";

const payloadString = (value: unknown): string => (typeof value === "string" && value !== "" ? value : "—");

/** 待决审批 + 批准/拒绝 (二次确认)。 */
function PendingApprovals() {
  const approvals = useApprovals();
  const decide = useDecideApproval();
  const [pending, setPending] = useState<{ approval: ApprovalRequest; decision: "approved" | "rejected" } | null>(null);

  const columns: Array<Column<ApprovalRequest>> = [
    { key: "approval_id", header: "approval_id", label: "approval_id", render: (row) => <ShortId value={row.approval_id} /> },
    { key: "session", header: "session_key", label: "session_key", render: (row) => <span className="mono small">{row.session_key}</span> },
    { key: "tool", header: "tool_name", label: "tool_name", render: (row) => <code className="code-inline">{row.tool_name}</code> },
    {
      key: "args",
      header: "参数摘要",
      label: "参数摘要",
      render: (row) => (
        <span className="small" title={row.args_summary}>
          {truncate(row.args_summary || "—", 100)}
        </span>
      ),
    },
    { key: "created", header: "发起时间", label: "发起时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
    {
      key: "elapsed",
      header: "已等待",
      label: "已等待",
      align: "right",
      render: (row) => <span className="tabular">{formatDuration(row.elapsed_seconds)}</span>,
    },
    {
      key: "actions",
      header: "裁决",
      label: "裁决",
      render: (row) => (
        <div className="row row--tight">
          <Button
            variant="primary"
            size="sm"
            data-testid={`approval-approve-${row.approval_id}`}
            disabled={decide.isPending}
            onClick={() => setPending({ approval: row, decision: "approved" })}
            accessibleName={`批准 ${row.tool_name} 调用`}
          >
            批准
          </Button>
          <Button
            variant="danger"
            size="sm"
            data-testid={`approval-reject-${row.approval_id}`}
            disabled={decide.isPending}
            onClick={() => setPending({ approval: row, decision: "rejected" })}
            accessibleName={`拒绝 ${row.tool_name} 调用`}
          >
            拒绝
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <Card
        title="待决审批 (HITL)"
        subtitle="GET /api/v1/approvals · tools_policy=ask 档的高危工具调用在这里等待人工裁决 (10s 自动刷新)"
      >
        <QueryState
          query={approvals}
          isEmpty={(data) => data.approvals.length === 0}
          empty={
            <p className="small muted">
              当前没有等待裁决的工具调用。审批门未接线 (control 未启用 HITL) 时这里会显示"功能未启用"而不是空表。
            </p>
          }
        >
          {(data) => (
            <div data-testid="approvals-pending-table">
              <Table ariaLabel="待决审批列表" columns={columns} rows={data.approvals} rowKey={(row) => row.approval_id} />
            </div>
          )}
        </QueryState>
      </Card>

      <ConfirmDialog
        open={pending !== null}
        title={pending?.decision === "approved" ? "批准工具调用" : "拒绝工具调用"}
        tone={pending?.decision === "approved" ? "primary" : "danger"}
        impact={
          pending ? (
            <span>
              {pending.decision === "approved" ? (
                <>
                  批准将<strong>立即放行</strong>该 ask 档高危工具调用:{" "}
                  <code className="code-inline">{pending.approval.tool_name}</code> 会以 Agent (
                  <code className="code-inline">{pending.approval.session_key}</code>) 的当前身份与权限真实执行,
                  参数摘要: {truncate(pending.approval.args_summary || "(无)", 80)}。
                </>
              ) : (
                <>
                  拒绝后该次 <code className="code-inline">{pending.approval.tool_name}</code> 调用不会执行,
                  Agent 收到拒绝结果并自行决定后续 (可能改走别的路径)。超时未裁决由后端 fail-closed 自动拒绝。
                </>
              )}
            </span>
          ) : (
            ""
          )
        }
        confirmLabel={pending?.decision === "approved" ? "确认批准并放行" : "确认拒绝"}
        loading={decide.isPending}
        onConfirm={() => {
          if (!pending) return;
          decide.mutate(
            { approvalId: pending.approval.approval_id, decision: pending.decision },
            { onSuccess: () => setPending(null) },
          );
        }}
        onCancel={() => setPending(null)}
      />
    </>
  );
}

/** 决策留痕: GET /approvals/history (事件里的 payload 含 decision/decider/reason)。 */
function ApprovalHistory() {
  const history = useApprovalHistory();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const columns: Array<Column<ApprovalDecisionRecord>> = [
    { key: "session", header: "session_key", label: "session_key", render: (row) => <span className="mono small">{row.session_key}</span> },
    { key: "seq", header: "seq", label: "seq", align: "right", render: (row) => <span className="tabular">{row.seq}</span> },
    { key: "type", header: "event_type", label: "event_type", render: (row) => <code className="code-inline">{row.event_type}</code> },
    { key: "time", header: "时间", label: "时间", render: (row) => <span className="nowrap">{formatTimestamp(row.timestamp)}</span> },
    {
      key: "decision",
      header: "decision",
      label: "decision",
      render: (row) => <Badge tone={statusTone(payloadString(row.payload.decision))}>{payloadString(row.payload.decision)}</Badge>,
    },
    { key: "decider", header: "decider", label: "decider", render: (row) => <span className="mono small">{payloadString(row.payload.decider)}</span> },
    { key: "reason", header: "reason", label: "reason", render: (row) => <span className="small">{payloadString(row.payload.reason)}</span> },
    {
      key: "payload",
      header: "payload",
      label: "payload",
      render: (row) => {
        const key = `${row.session_key}|${row.seq}`;
        const open = expanded.has(key);
        return (
          <div className="stack stack--tight">
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                setExpanded((current) => {
                  const next = new Set(current);
                  if (next.has(key)) next.delete(key);
                  else next.add(key);
                  return next;
                })
              }
              accessibleName={`${open ? "收起" : "展开"}该决策事件的完整 payload`}
            >
              {open ? "收起" : "展开"}
            </Button>
            {open ? <CodeBlock ariaLabel="审批决策事件 payload" maxHeight="16rem">{prettyJson(row.payload)}</CodeBlock> : null}
          </div>
        );
      },
    },
  ];

  return (
    <Card title="决策留痕" subtitle="GET /api/v1/approvals/history · tool.called / tool.outcome 事件流 (含 decision / decider / reason)">
      <QueryState
        query={history}
        isEmpty={(data) => data.events.length === 0}
        empty={<p className="small muted">尚无审批决策记录。</p>}
      >
        {(data) => (
          <div data-testid="approvals-history-table">
            <Table ariaLabel="审批决策留痕" compact responsive columns={columns} rows={data.events} rowKey={(row, index) => `${row.session_key}|${row.seq}|${index}`} />
          </div>
        )}
      </QueryState>
    </Card>
  );
}

/**
 * 审批 (HITL) tab: 待决列表 + 裁决 (二次确认) + 决策留痕。
 * 审批门未接线时读端点 404 → QueryState 渲染 unavailable, 不伪装成"无待审批"。
 */
export default function ApprovalsTab() {
  return (
    <div className="stack" data-testid="approvals-tab">
      <Callout tone="warning" title="批准 = 放行高危工具">
        <span className="small">
          ask 档工具是 Agent 主动请求人工裁决的高危调用 (tools_policy 配置)。批准即以其当前身份真实执行,
          决策与理由会写入留痕 (下方历史); 超时未裁决由后端 fail-closed 拒绝, 不会默认放行。
        </span>
      </Callout>
      <PendingApprovals />
      <ApprovalHistory />
    </div>
  );
}
