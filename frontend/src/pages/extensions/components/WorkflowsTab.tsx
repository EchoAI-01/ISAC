import { isApiError } from "@/api/errors";
import type { WorkflowDto } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useStartWorkflow } from "@/hooks/mutations";
import { useWorkflows } from "@/hooks/queries";
import { useState } from "react";

/**
 * 工作流 tab: GET /workflows 清单 + 启动。
 *
 * control.workflow.enabled=false 时读端点不挂载 → QueryState 渲染
 * unavailable (configHint 指向开关), 不假装"暂无工作流"。
 */
export default function WorkflowsTab() {
  const workflows = useWorkflows();
  const start = useStartWorkflow();
  const [startUnavailable, setStartUnavailable] = useState(false);

  const columns: Array<Column<WorkflowDto>> = [
    { key: "workflow_id", header: "workflow_id", label: "workflow_id", render: (row) => <code className="code-inline">{row.workflow_id}</code> },
    { key: "name", header: "名称", label: "名称", render: (row) => row.name || "—" },
    { key: "status", header: "状态", label: "状态", render: (row) => <Badge tone={statusTone(row.status)} dot>{row.status}</Badge> },
    { key: "stages", header: "阶段数", label: "阶段数", align: "right", render: (row) => <span className="tabular">{row.stages}</span> },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button
          variant="primary"
          size="sm"
          data-testid={`workflows-start-${row.workflow_id}`}
          disabled={start.isPending}
          loading={start.isPending && start.variables === row.workflow_id}
          onClick={() =>
            start.mutate(row.workflow_id, {
              onError: (error) => {
                if (isApiError(error) && error.kind === "unavailable") setStartUnavailable(true);
              },
            })
          }
          accessibleName={`启动工作流 ${row.workflow_id}`}
        >
          启动
        </Button>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="extensions-workflows">
      {startUnavailable ? (
        <Callout tone="warning" title="工作流启动端点未挂载">
          <span className="small">
            后端返回 404/405: 工作流子系统未启用。请在 System 域把{" "}
            <code className="code-inline">control.workflow.enabled</code> 设为{" "}
            <code className="code-inline">true</code> (该节属 restart_required, 需重启生效)。
          </span>
        </Callout>
      ) : null}

      <Card title="已注册工作流" subtitle="GET /api/v1/workflows · 返回数组; 启动后可在 Sessions & Tasks 域跟踪其任务">
        <QueryState
          query={workflows}
          isEmpty={(rows) => rows.length === 0}
          empty={
            <p className="small muted">
              没有已注册的工作流 (插件未提供 workflow, 或工作流子系统未启用 —— 未启用时本页会显示"功能未启用"而不是空表)。
            </p>
          }
        >
          {(rows) => (
            <div data-testid="workflows-table">
              <Table ariaLabel="工作流列表" columns={columns} rows={rows} rowKey={(row) => row.workflow_id} />
            </div>
          )}
        </QueryState>
      </Card>
    </div>
  );
}
