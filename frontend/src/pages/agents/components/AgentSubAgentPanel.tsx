import { Link } from "react-router-dom";

import { isTerminalStatus } from "@/api/subagent";
import type { SubAgentRun } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { ShortId } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useCancelSubAgentRun } from "@/hooks/mutations";
import { useAgentSubAgentRuns } from "@/hooks/queries";
import { formatDuration, formatRelative, formatTokens, truncate } from "@/lib/format";
import { useNowSeconds } from "@/lib/time";

/**
 * Agent 详情页的"子任务" tab (紧凑视图)。
 *
 * 完整能力 (事件时间线 / afterSeq 增量) 在 Sessions & Tasks 域; 这里只列该
 * Agent 名下的运行清单 + 取消入口, 详情跳转过去, 不重复实现两套时间线。
 * §8.4 隐私: 不渲染 reasoning / 凭据 / 完整文件内容 (后端也不返回)。
 */
export default function AgentSubAgentPanel({ agentId }: { agentId: string }) {
  const runs = useAgentSubAgentRuns(agentId);
  const cancel = useCancelSubAgentRun();
  const nowSeconds = useNowSeconds();

  const columns: Array<Column<SubAgentRun>> = [
    {
      key: "task_id",
      header: "task_id",
      label: "task_id",
      render: (row) => (
        <Link to={`/sessions?tab=subagents&task=${encodeURIComponent(row.task_id)}`}>
          <ShortId value={row.task_id} />
        </Link>
      ),
    },
    {
      key: "status",
      header: "状态",
      label: "状态",
      render: (row) => (
        <Badge tone={statusTone(row.status)} dot>
          {row.status}
        </Badge>
      ),
    },
    { key: "phase", header: "phase", label: "phase", render: (row) => <code className="code-inline">{row.phase || "—"}</code> },
    {
      key: "elapsed",
      header: "耗时",
      label: "耗时",
      align: "right",
      render: (row) => (
        <span className="tabular">
          {formatDuration((row.finished_at || nowSeconds) - row.started_at)}
        </span>
      ),
    },
    { key: "tokens", header: "tokens", label: "tokens", align: "right", render: (row) => <span className="tabular">{formatTokens(row.tokens_used)}</span> },
    { key: "tools", header: "工具调用", label: "工具调用", align: "right", render: (row) => <span className="tabular">{row.tool_calls_used}</span> },
    {
      key: "result",
      header: "结果 / 错误",
      label: "结果 / 错误",
      render: (row) =>
        row.error_code ? (
          <span className="small">
            <Badge tone="danger">{row.error_code}</Badge> {truncate(row.error_summary || "", 60)}
          </span>
        ) : (
          <span className="small muted">{truncate(row.result_summary || "—", 60)}</span>
        ),
    },
    {
      key: "updated",
      header: "更新",
      label: "更新",
      render: (row) => <span className="nowrap small">{formatRelative(row.updated_at, nowSeconds)}</span>,
    },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button
          variant="ghost"
          size="sm"
          disabled={isTerminalStatus(row.status) || cancel.isPending}
          onClick={() => cancel.mutate(row.task_id)}
          accessibleName={`取消子任务 ${row.task_id}`}
        >
          取消
        </Button>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="agent-subagent-runs">
      <QueryState
        query={runs}
        isEmpty={(rows) => rows.length === 0}
        empty={
          <p className="small muted">
            该 Agent 尚未派发过 SubAgent 任务。派发后这里显示运行清单; 事件时间线在{" "}
            <Link to="/sessions?tab=subagents">Sessions &amp; Tasks → SubAgent 任务</Link>。
          </p>
        }
      >
        {(rows) => (
          <Table
            ariaLabel={`Agent ${agentId} 的 SubAgent 任务`}
            compact
            columns={columns}
            rows={rows}
            rowKey={(row) => row.task_id}
          />
        )}
      </QueryState>
      <p className="small muted">
        取消是幂等请求: 任务已处终态时返回原终态, 不代表本次取消生效 (以返回的 status 为准)。
        evidence_refs / usage 明细与事件时间线请到 Sessions &amp; Tasks 域查看。
      </p>
    </div>
  );
}
