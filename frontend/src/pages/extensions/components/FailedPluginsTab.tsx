import { useState } from "react";

import type { PluginActionResult } from "@/api/types";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useRetryPlugin } from "@/hooks/mutations";
import { useFailedPlugins } from "@/hooks/queries";

import PluginActionResultPanel from "./PluginActionResultPanel";

interface FailureRow {
  name: string;
  message: string;
}

/**
 * 失败 tab (F4 验收: "失败插件可重试")。
 *
 * GET /plugins/failed 的 failures 是**对象** (name → 错误信息), 不是数组;
 * 清单只存在于进程内存, 重启后清空 —— 页面如实说明, 不做持久化假象。
 */
export default function FailedPluginsTab() {
  const failed = useFailedPlugins();
  const retry = useRetryPlugin();
  const [lastResult, setLastResult] = useState<{ result: PluginActionResult; name: string } | null>(null);

  const columns: Array<Column<FailureRow>> = [
    { key: "name", header: "插件名", label: "插件名", render: (row) => <code className="code-inline">{row.name}</code> },
    {
      key: "message",
      header: "失败原因",
      label: "失败原因",
      render: (row) => (
        <span className="small" title={row.message}>
          {row.message || "(后端未提供错误信息)"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button
          variant="secondary"
          size="sm"
          data-testid={`plugins-retry-${row.name}`}
          disabled={retry.isPending}
          loading={retry.isPending && retry.variables === row.name}
          onClick={() =>
            retry.mutate(row.name, {
              onSuccess: (result) => setLastResult({ result, name: row.name }),
            })
          }
          accessibleName={`重试安装插件 ${row.name}`}
        >
          重试
        </Button>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="plugins-failed">
      {lastResult ? (
        <PluginActionResultPanel result={lastResult.result} action={`重试 ${lastResult.name} `} />
      ) : null}

      <Callout tone="warning" title="失败清单不持久化">
        <span className="small">
          失败清单只存在于<strong>进程内存</strong>: 后端重启后即清空 (即使插件仍然装不上)。
          重试会重新执行完整安装流程, 结果 (status 与运行中 Agent 同步明细) 显示在上方;
          反复失败时请结合"日志与审计"域的实时日志定位 (按插件名过滤)。
        </span>
      </Callout>

      <Card title="加载失败的插件" subtitle="GET /api/v1/plugins/failed · failures: name → 错误信息">
        <QueryState
          query={failed}
          isEmpty={(data) => Object.keys(data.failures).length === 0}
          empty={<p className="small muted">当前进程内没有加载失败的插件记录。</p>}
        >
          {(data) => {
            const rows: FailureRow[] = Object.entries(data.failures).map(([name, message]) => ({ name, message }));
            return (
              <div data-testid="plugins-failed-table">
                <Table ariaLabel="加载失败的插件" columns={columns} rows={rows} rowKey={(row) => row.name} />
              </div>
            );
          }}
        </QueryState>
      </Card>
    </div>
  );
}
