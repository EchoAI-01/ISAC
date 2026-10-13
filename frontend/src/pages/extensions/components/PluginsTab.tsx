import { useState } from "react";

import type { LoadedPlugin, PluginActionResult } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useReloadPlugin, useUninstallPlugin } from "@/hooks/mutations";
import { useLoadedPlugins } from "@/hooks/queries";

import PluginActionResultPanel from "./PluginActionResultPanel";

/**
 * 插件 tab: 已加载清单 (name + 运行形态) + 热重载 / 卸载。
 *
 * 卸载不可逆 (共享注册表与运行中 Agent 的来源条目一并清理) → requireText。
 * isolated=true 表示插件跑在隔离子进程 (崩溃不拖垮宿主)。
 */
export default function PluginsTab() {
  const plugins = useLoadedPlugins();
  const reload = useReloadPlugin();
  const uninstall = useUninstallPlugin();
  const [pendingUninstall, setPendingUninstall] = useState<LoadedPlugin | null>(null);
  const [lastResult, setLastResult] = useState<{ result: PluginActionResult; action: string } | null>(null);

  const columns: Array<Column<LoadedPlugin>> = [
    { key: "name", header: "插件名", label: "插件名", render: (row) => <code className="code-inline">{row.name}</code> },
    {
      key: "isolated",
      header: "运行形态",
      label: "运行形态",
      render: (row) => (
        <Badge tone={row.isolated ? "info" : "neutral"} dot title={row.isolated ? "独立子进程运行, 崩溃不影响宿主" : "与宿主同进程运行"}>
          {row.isolated ? "隔离子进程" : "宿主进程内"}
        </Badge>
      ),
    },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <div className="row row--tight">
          <Button
            variant="secondary"
            size="sm"
            disabled={reload.isPending}
            loading={reload.isPending && reload.variables === row.name}
            onClick={() =>
              reload.mutate(row.name, {
                onSuccess: (result) => setLastResult({ result, action: `重载 ${row.name} ` }),
              })
            }
            accessibleName={`热重载插件 ${row.name}`}
          >
            热重载
          </Button>
          <Button
            variant="danger"
            size="sm"
            disabled={uninstall.isPending}
            onClick={() => setPendingUninstall(row)}
            accessibleName={`卸载插件 ${row.name}`}
          >
            卸载
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="stack">
      <PluginActionResultPanel result={lastResult?.result ?? null} action={lastResult?.action ?? ""} />

      <Card title="已加载插件" subtitle="GET /api/v1/plugins/loaded · 热重载重新执行插件 setup, 卸载清理注册表与运行中 Agent 的来源条目">
        <QueryState
          query={plugins}
          isEmpty={(data) => data.plugins.length === 0}
          empty={
            <p className="small muted">
              没有已加载的插件。到"市场" tab 安装, 或检查全局配置 plugins 节。
            </p>
          }
        >
          {(data) => (
            <div data-testid="plugins-loaded-table">
              <Table ariaLabel="已加载插件" columns={columns} rows={data.plugins} rowKey={(row) => row.name} />
            </div>
          )}
        </QueryState>
      </Card>

      <ConfirmDialog
        open={pendingUninstall !== null}
        title={pendingUninstall ? `卸载插件: ${pendingUninstall.name}` : "卸载插件"}
        tone="danger"
        requireText={pendingUninstall?.name ?? ""}
        confirmLabel="卸载插件"
        impact={
          pendingUninstall ? (
            <span>
              卸载 <code className="code-inline">{pendingUninstall.name}</code> 会移除共享注册表条目、
              删除已下载的插件文件, 并从所有运行中 Agent 摘除该插件的工具 / 命令 / 注入器 ——
              <strong>不可恢复</strong>, 重装需要重新从市场或 git/url 安装。
            </span>
          ) : (
            ""
          )
        }
        loading={uninstall.isPending}
        onConfirm={() => {
          if (!pendingUninstall) return;
          const name = pendingUninstall.name;
          uninstall.mutate(name, {
            onSuccess: (result) => {
              setLastResult({ result, action: `卸载 ${name} ` });
              setPendingUninstall(null);
            },
          });
        }}
        onCancel={() => setPendingUninstall(null)}
      />
    </div>
  );
}
