import { isTerminalStatus } from "@/api/subagent";
import type { SubAgentEvent, SubAgentRun } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { KeyValue, ShortId } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useCancelSubAgentRun } from "@/hooks/mutations";
import { useSubAgentEvents, useSubAgentRuns } from "@/hooks/queries";
import { useUrlString } from "@/hooks/useUrlState";
import { formatDuration, formatTimestamp, formatTokens, truncate } from "@/lib/format";
import { useNowSeconds } from "@/lib/time";

/** 单个任务的事件时间线 (§8.4: 只有脱敏后的摘要字段, 无 reasoning / 凭据 / 文件内容)。 */
function TaskEventsPanel({ run }: { run: SubAgentRun }) {
  const events = useSubAgentEvents(run.task_id);

  const columns: Array<Column<SubAgentEvent>> = [
    { key: "seq", header: "seq", label: "seq", align: "right", render: (row) => <span className="tabular">{row.seq}</span> },
    { key: "type", header: "event_type", label: "event_type", render: (row) => <code className="code-inline">{row.event_type}</code> },
    { key: "time", header: "时间", label: "时间", render: (row) => <span className="nowrap">{formatTimestamp(row.timestamp)}</span> },
    { key: "tool", header: "tool_name", label: "tool_name", render: (row) => (row.tool_name ? <span className="mono small">{row.tool_name}</span> : "—") },
    {
      key: "summary",
      header: "summary",
      label: "summary",
      render: (row) => (
        <span className="small" title={row.summary}>
          {truncate(row.summary || "—", 120)}
        </span>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="subagent-events">
      <KeyValue
        items={[
          { term: "task_id", value: <span className="mono">{run.task_id}</span> },
          { term: "parent_agent", value: <span className="mono">{run.parent_agent_id}</span> },
          {
            term: "status / phase",
            value: (
              <span className="row row--tight">
                <Badge tone={statusTone(run.status)} dot>{run.status}</Badge>
                <code className="code-inline">{run.phase || "—"}</code>
              </span>
            ),
          },
          { term: "tokens_used", value: formatTokens(run.tokens_used) },
          { term: "tool_calls_used", value: String(run.tool_calls_used) },
          { term: "evidence_refs", value: `${run.evidence_refs.length} 条` },
          {
            term: "结果 / 错误",
            value: run.error_code ? (
              <span>
                <Badge tone="danger">{run.error_code}</Badge> {run.error_summary || "—"}
              </span>
            ) : (
              truncate(run.result_summary || "—", 160)
            ),
          },
        ]}
      />

      <Card title="事件时间线" subtitle="GET /subagent-runs/{task}/events · 服务端只返回脱敏摘要字段">
        <QueryState
          query={events}
          isEmpty={(data) => data.events.length === 0}
          empty={<p className="small muted">该任务尚无事件记录。</p>}
        >
          {(data) => (
            <Table ariaLabel={`任务 ${run.task_id} 的事件时间线`} compact columns={columns} rows={data.events} rowKey={(row) => String(row.seq)} />
          )}
        </QueryState>
      </Card>
    </div>
  );
}

/**
 * SubAgent 任务 tab (§8.4 隐私边界)。
 *
 * 清单 GET /subagent-runs (数组) + 详情 (?task= 写 URL, 从 Agent 详情页跳转可直达)
 * + 取消 (幂等: 已终态返回原终态 ≠ 取消生效, 以返回 status 为准, mutation 已按此提示)。
 * 后端不返回 reasoning / 凭据 / 完整文件内容, 前端也不造这些字段。
 */
export default function SubAgentsTab() {
  const [selectedTask, setSelectedTask] = useUrlString("task");
  const runs = useSubAgentRuns();
  const cancel = useCancelSubAgentRun();
  const nowSeconds = useNowSeconds();

  const selected = (runs.data ?? []).find((run) => run.task_id === selectedTask) ?? null;

  const columns: Array<Column<SubAgentRun>> = [
    {
      key: "task_id",
      header: "task_id",
      label: "task_id",
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => setSelectedTask(row.task_id)} accessibleName={`查看任务 ${row.task_id} 详情`}>
          <ShortId value={row.task_id} />
        </Button>
      ),
    },
    { key: "parent", header: "parent_agent", label: "parent_agent_id", render: (row) => <span className="mono small">{row.parent_agent_id}</span> },
    { key: "status", header: "状态", label: "状态", render: (row) => <Badge tone={statusTone(row.status)} dot>{row.status}</Badge> },
    { key: "phase", header: "phase", label: "phase", render: (row) => <code className="code-inline">{row.phase || "—"}</code> },
    {
      key: "elapsed",
      header: "耗时",
      label: "耗时",
      align: "right",
      render: (row) => <span className="tabular">{formatDuration((row.finished_at || nowSeconds) - row.started_at)}</span>,
    },
    { key: "tokens", header: "tokens", label: "tokens_used", align: "right", render: (row) => <span className="tabular">{formatTokens(row.tokens_used)}</span> },
    { key: "tools", header: "工具调用", label: "tool_calls_used", align: "right", render: (row) => <span className="tabular">{row.tool_calls_used}</span> },
    { key: "evidence", header: "evidence", label: "evidence_refs 数量", align: "right", render: (row) => <span className="tabular">{row.evidence_refs.length}</span> },
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
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <div className="row row--tight">
          <Button variant="ghost" size="sm" onClick={() => setSelectedTask(row.task_id)} accessibleName={`任务 ${row.task_id} 详情`}>
            详情
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={isTerminalStatus(row.status) || cancel.isPending}
            title={isTerminalStatus(row.status) ? "任务已处终态, 无法取消" : undefined}
            onClick={() => cancel.mutate(row.task_id)}
            accessibleName={`取消任务 ${row.task_id}`}
          >
            取消
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="subagents-tab">
      <Callout tone="info" title="隐私边界 (§8.4)">
        <span className="small">
          SubAgent 事件与结果只暴露<strong>脱敏摘要</strong> (summary / tool_name / 错误码与摘要);
          reasoning 过程、凭据、完整文件内容后端一律不返回, 本页也不会渲染。取消是幂等请求:
          任务已处终态时返回原终态, <strong>不等于本次取消生效</strong> —— 以返回的 status 为准。
        </span>
      </Callout>

      <Card title="SubAgent 任务" subtitle="GET /api/v1/subagent-runs · 全部 Agent 派发的子任务 (点 task_id 看事件时间线)">
        <QueryState
          query={runs}
          isEmpty={(rows) => rows.length === 0}
          empty={<p className="small muted">尚无 SubAgent 任务记录。</p>}
        >
          {(rows) => (
            <div data-testid="subagents-table">
              <Table ariaLabel="SubAgent 任务列表" compact responsive columns={columns} rows={rows} rowKey={(row) => row.task_id} />
            </div>
          )}
        </QueryState>
      </Card>

      {selectedTask !== "" ? (
        selected ? (
          <Card
            title={
              <span className="row row--tight">
                任务详情 <ShortId value={selected.task_id} max={16} />
              </span>
            }
            actions={
              <Button variant="ghost" size="sm" onClick={() => setSelectedTask("")} accessibleName="关闭任务详情">
                关闭
              </Button>
            }
          >
            <TaskEventsPanel run={selected} />
          </Card>
        ) : (
          <Callout tone="warning" title="URL 里的 task 不在当前清单中">
            <span className="small">
              <code className="code-inline">{selectedTask}</code> 未出现在 GET /subagent-runs 的结果里 (任务记录可能已过期清理, 或无权限查看)。
            </span>
          </Callout>
        )
      ) : null}
    </div>
  );
}
