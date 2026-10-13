import { useState } from "react";
import { Link } from "react-router-dom";

import type { AgentSummary } from "@/api/types";
import { agentStatusTone, Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/Card";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useAgentLifecycle } from "@/hooks/mutations";
import { useAgents } from "@/hooks/queries";

import AgentCreateModal from "./components/AgentCreateModal";
import AgentDestroyDialog from "./components/AgentDestroyDialog";

/**
 * Agents 域列表页 (§8.1 IA 第 2 行)。
 *
 * 快捷操作: 启动 / 停止 / 详情 / 销毁。销毁是不可逆操作 → ConfirmDialog
 * + requireText(agent_id) + keep_memory 开关 (语义见 AgentDestroyDialog)。
 */
export default function AgentsPage() {
  const agents = useAgents();
  const lifecycle = useAgentLifecycle();
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDestroy, setPendingDestroy] = useState<string | null>(null);

  const columns: Array<Column<AgentSummary>> = [
    {
      key: "agent_id",
      header: "agent_id",
      label: "agent_id",
      render: (row) => (
        <Link to={`/agents/${encodeURIComponent(row.agent_id)}`} className="mono">
          {row.agent_id}
        </Link>
      ),
    },
    {
      key: "status",
      header: "状态",
      label: "状态",
      render: (row) => (
        <Badge tone={agentStatusTone(row.status)} dot>
          {row.status}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "快捷操作",
      label: "快捷操作",
      render: (row) => {
        const running = row.status === "running";
        return (
          <div className="row row--tight">
            <Button
              variant="secondary"
              size="sm"
              disabled={running || lifecycle.start.isPending}
              loading={lifecycle.start.isPending && lifecycle.start.variables === row.agent_id}
              onClick={() => lifecycle.start.mutate(row.agent_id)}
              accessibleName={`启动 ${row.agent_id}`}
            >
              启动
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!running || lifecycle.stop.isPending}
              loading={lifecycle.stop.isPending && lifecycle.stop.variables === row.agent_id}
              onClick={() => lifecycle.stop.mutate(row.agent_id)}
              accessibleName={`停止 ${row.agent_id}`}
            >
              停止
            </Button>
            <Link className="btn btn--secondary btn--sm" to={`/agents/${encodeURIComponent(row.agent_id)}`}>
              详情
            </Link>
            <Button
              variant="danger"
              size="sm"
              disabled={lifecycle.destroy.isPending}
              onClick={() => setPendingDestroy(row.agent_id)}
              accessibleName={`销毁 ${row.agent_id}`}
            >
              销毁
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="stack">
      <PageHeader
        title="Agents"
        description="状态、人格、门控、模型能力、工具/插件/MCP、记忆命名空间"
        actions={
          <Button variant="primary" data-testid="agents-create-open" onClick={() => setCreateOpen(true)}>
            创建 Agent
          </Button>
        }
      />

      <QueryState
        query={agents}
        isEmpty={(rows) => rows.length === 0}
        empty={
          <div className="stack stack--tight">
            <p className="muted">尚未创建任何 Agent。创建走后端受限默认模板 (能力字段最小化), 之后在详情页显式授予能力。</p>
            <div>
              <Button variant="primary" onClick={() => setCreateOpen(true)}>
                创建第一个 Agent
              </Button>
            </div>
          </div>
        }
      >
        {(rows) => (
          <div data-testid="agents-table">
            <Table
              ariaLabel="Agent 列表"
              columns={columns}
              rows={rows}
              rowKey={(row) => row.agent_id}
            />
          </div>
        )}
      </QueryState>

      <AgentCreateModal open={createOpen} onClose={() => setCreateOpen(false)} />
      <AgentDestroyDialog agentId={pendingDestroy} onClose={() => setPendingDestroy(null)} />
    </div>
  );
}
