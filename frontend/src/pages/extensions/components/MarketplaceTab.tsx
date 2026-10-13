import { useState } from "react";

import { isApiError } from "@/api/errors";
import type { MarketplacePlugin, PluginActionResult, PluginInstallSource } from "@/api/types";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { TextField } from "@/components/Form";
import { SegmentedControl } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { UnavailableState } from "@/components/StateViews";
import { Table, type Column } from "@/components/Table";
import { useInstallPlugin } from "@/hooks/mutations";
import { useMarketplace } from "@/hooks/queries";

import PluginActionResultPanel from "./PluginActionResultPanel";

type ExternalSourceType = "git" | "url";

/**
 * 市场 tab (F4 验收核心)。
 *
 * - 清单 = data/plugin_marketplace.jsonc 与远程清单合并 (GET /plugins/marketplace);
 * - 一键安装 source={type:"market", name}; 另提供 git / url 安装表单;
 * - control.plugins.allow_install=false 时写端点 404/405 → 渲染 UnavailableState
 *   (不隐藏按钮假装可装, 也不把错误吞成"安装失败");
 * - 安装结果显示 status + sync (哪些运行中 Agent 同步到了哪些工具)。
 */
export default function MarketplaceTab() {
  const [refresh, setRefresh] = useState(false);
  const marketplace = useMarketplace(refresh);
  const install = useInstallPlugin();

  const [lastResult, setLastResult] = useState<{ result: PluginActionResult; action: string } | null>(null);
  const [installUnavailable, setInstallUnavailable] = useState(false);

  const [sourceType, setSourceType] = useState<ExternalSourceType>("git");
  const [repoUrl, setRepoUrl] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [packageName, setPackageName] = useState("");

  const runInstall = (source: PluginInstallSource, action: string) => {
    install.mutate(source, {
      onSuccess: (result) => {
        setInstallUnavailable(false);
        setLastResult({ result, action });
      },
      onError: (error) => {
        if (isApiError(error) && error.kind === "unavailable") setInstallUnavailable(true);
      },
    });
  };

  const externalOk =
    sourceType === "git" ? repoUrl.trim() !== "" : fileUrl.trim() !== "";

  const submitExternal = () => {
    if (!externalOk) return;
    const name = packageName.trim() === "" ? undefined : packageName.trim();
    if (sourceType === "git") {
      runInstall({ type: "git", repo_url: repoUrl.trim(), ...(name ? { name } : {}) }, `从 git 安装 ${repoUrl.trim()} `);
    } else {
      runInstall({ type: "url", url: fileUrl.trim(), ...(name ? { name } : {}) }, `从 url 安装 ${fileUrl.trim()} `);
    }
  };

  const columns: Array<Column<MarketplacePlugin>> = [
    { key: "name", header: "插件名", label: "插件名", render: (row) => <code className="code-inline">{row.name}</code> },
    { key: "description", header: "描述", label: "描述", render: (row) => <span className="small">{row.description || "—"}</span> },
    { key: "version", header: "版本", label: "版本", render: (row) => <span className="mono small">{row.version || "—"}</span> },
    { key: "author", header: "作者", label: "作者", render: (row) => row.author || "—" },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button
          variant="primary"
          size="sm"
          data-testid={`plugins-install-${row.name}`}
          disabled={install.isPending}
          loading={install.isPending && install.variables?.type === "market" && install.variables?.name === row.name}
          onClick={() => runInstall({ type: "market", name: row.name }, `安装 ${row.name} `)}
          accessibleName={`从市场安装插件 ${row.name}`}
        >
          安装
        </Button>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="plugins-marketplace">
      <PluginActionResultPanel result={lastResult?.result ?? null} action={lastResult?.action ?? ""} />

      {installUnavailable ? (
        <UnavailableState
          title="插件安装未启用 (写端点返回 404/405)"
          description="后端 control.plugins.allow_install = false 时, /plugins/install 不挂载; 市场清单仍可读, 但无法安装。"
          configHint="control.plugins.allow_install = true"
        />
      ) : null}

      <Card
        title="插件市场清单"
        subtitle="GET /api/v1/plugins/marketplace · 本地 data/plugin_marketplace.jsonc 与远程清单合并"
        actions={
          <Button variant="secondary" size="sm" data-testid="plugins-marketplace-refresh" onClick={() => setRefresh((current) => !current)} loading={marketplace.isFetching}>
            刷新远程清单
          </Button>
        }
      >
        <QueryState
          query={marketplace}
          isEmpty={(data) => data.plugins.length === 0}
          empty={
            <p className="small muted">
              市场清单为空: 本地 data/plugin_marketplace.jsonc 没有条目, 且远程清单不可达或未配置。可点"刷新远程清单"重试, 或用下方 git / url 安装。
            </p>
          }
        >
          {(data) => (
            <div data-testid="plugins-marketplace-table">
              <Table ariaLabel="插件市场清单" columns={columns} rows={data.plugins} rowKey={(row) => row.name} />
            </div>
          )}
        </QueryState>
      </Card>

      <Card title="从 git / url 安装" subtitle="POST /api/v1/plugins/install · source = {type: git|url, ...}; 安装是写操作, 会记入审计">
        <div className="stack">
          <div className="row row--tight">
            <span className="toolbar__label" id="install-source-type-label">
              来源类型
            </span>
            <SegmentedControl
              ariaLabel="外部安装来源类型"
              options={[
                { value: "git", label: "git 仓库" },
                { value: "url", label: "url 压缩包" },
              ]}
              value={sourceType}
              onChange={(next) => setSourceType(next as ExternalSourceType)}
            />
          </div>

          {sourceType === "git" ? (
            <TextField
              label="repo_url"
              mono
              required
              hint="插件 git 仓库地址 (https / ssh); 后端克隆后按插件规范加载"
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
            />
          ) : (
            <TextField
              label="url"
              mono
              required
              hint="插件压缩包 (zip) 的直链 URL"
              value={fileUrl}
              onChange={(event) => setFileUrl(event.target.value)}
            />
          )}

          <TextField
            label="name (可选)"
            mono
            hint="覆盖插件包内声明的名称; 留空使用清单/包内名称"
            value={packageName}
            onChange={(event) => setPackageName(event.target.value)}
          />

          <div className="row row--tight">
            <Button
              variant="primary"
              data-testid="plugins-install-external-submit"
              disabled={!externalOk || install.isPending}
              loading={install.isPending}
              onClick={submitExternal}
            >
              安装
            </Button>
            <span className="small muted">安装结果 (status 与运行中 Agent 的工具同步明细) 会显示在页面顶部。</span>
          </div>
        </div>
      </Card>

      <Callout tone="info" title="安装语义">
        <span className="small">
          安装成功后插件进入共享注册表, 并按各运行中 Agent 的启用矩阵 (plugins_allow / plugins_deny)
          决定实际同步给谁 —— 结果面板里的 sync 就是逐 Agent 的同步明细。新 Agent 默认模板不含任何插件,
          需要在 Agent 详情 → 插件矩阵里显式放开。
        </span>
      </Callout>
    </div>
  );
}
