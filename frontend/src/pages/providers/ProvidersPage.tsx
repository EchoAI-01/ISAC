import { useState } from "react";

import type { ArtifactMeta, ModelDescriptor, ProviderSummary } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card, PageHeader } from "@/components/Card";
import { ShortId } from "@/components/DataDisplay";
import { SelectField } from "@/components/Form";
import { CopyButton } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useDeleteArtifact, useTestProvider } from "@/hooks/mutations";
import { useArtifacts, useModels, useProviders } from "@/hooks/queries";
import { useUrlString } from "@/hooks/useUrlState";
import { formatBytes, formatDuration, formatTimestamp } from "@/lib/format";
import { useNowSeconds } from "@/lib/time";

const ALL = "";

function distinct(values: string[]): string[] {
  return [...new Set(values.filter((value) => value !== ""))].sort();
}

/** Provider 列表 + 连通性测试。测试是写操作 (后端会记审计事件)。 */
function ProvidersSection() {
  const providers = useProviders();
  const test = useTestProvider();

  const columns: Array<Column<ProviderSummary>> = [
    { key: "provider_id", header: "provider_id", label: "provider_id", render: (row) => <code className="code-inline">{row.provider_id}</code> },
    { key: "model_id", header: "默认 model_id", label: "默认 model_id", render: (row) => <span className="mono">{row.model_id || "—"}</span> },
    {
      key: "actions",
      header: "连通性测试",
      label: "连通性测试",
      render: (row) => (
        <div className="row row--tight">
          <Button
            variant="secondary"
            size="sm"
            data-testid={`provider-test-${row.provider_id}`}
            disabled={test.isPending}
            loading={test.isPending && test.variables?.providerId === row.provider_id}
            onClick={() => test.mutate({ providerId: row.provider_id, modelId: row.model_id || undefined })}
            accessibleName={`测试 Provider ${row.provider_id} 连通性`}
          >
            测试
          </Button>
          {test.data && test.variables?.providerId === row.provider_id ? (
            <Badge tone={statusTone(test.data.status)} dot>
              {test.data.status}
            </Badge>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <Card
      title="Provider 列表"
      subtitle="GET /api/v1/providers · 连通性测试会真实调用一次 Provider 并写入审计日志"
    >
      <QueryState
        query={providers}
        isEmpty={(data) => data.providers.length === 0}
        empty={
          <p className="small muted">
            尚未配置任何 LLM Provider。在 config.jsonc 的 providers 节配置并重启后, 或通过全局配置热更新 (System 域) 添加。
          </p>
        }
      >
        {(data) => (
          <div data-testid="providers-table">
            <Table ariaLabel="Provider 列表" columns={columns} rows={data.providers} rowKey={(row) => `${row.provider_id}|${row.model_id}`} />
          </div>
        )}
      </QueryState>
    </Card>
  );
}

/** 模型目录 + provider/operation/cost_tier 筛选 (URL 状态)。 */
function ModelsSection() {
  const models = useModels();
  const [providerFilter, setProviderFilter] = useUrlString("provider");
  const [operationFilter, setOperationFilter] = useUrlString("operation");
  const [costTierFilter, setCostTierFilter] = useUrlString("cost_tier");

  const all = models.data?.models ?? [];
  const providerOptions = distinct(all.map((model) => model.provider_id));
  const operationOptions = distinct(all.flatMap((model) => model.operations));
  const costTierOptions = distinct(all.map((model) => model.cost_tier));

  const filtered = all.filter(
    (model) =>
      (providerFilter === ALL || model.provider_id === providerFilter) &&
      (operationFilter === ALL || model.operations.includes(operationFilter)) &&
      (costTierFilter === ALL || model.cost_tier === costTierFilter),
  );

  const columns: Array<Column<ModelDescriptor>> = [
    { key: "provider", header: "provider", label: "provider", render: (row) => <code className="code-inline">{row.provider_id}</code> },
    { key: "model", header: "model", label: "model", render: (row) => <span className="mono">{row.model_id}</span> },
    {
      key: "operations",
      header: "operations",
      label: "operations",
      render: (row) => (
        <span className="row row--tight" style={{ flexWrap: "wrap" }}>
          {row.operations.map((operation) => (
            <Badge key={operation}>{operation}</Badge>
          ))}
        </span>
      ),
    },
    { key: "in", header: "modalities_in", label: "modalities_in", render: (row) => <span className="small">{row.modalities_in.join(", ") || "—"}</span> },
    { key: "out", header: "modalities_out", label: "modalities_out", render: (row) => <span className="small">{row.modalities_out.join(", ") || "—"}</span> },
    { key: "cost", header: "cost_tier", label: "cost_tier", render: (row) => <Badge tone={row.cost_tier === "high" ? "warning" : "neutral"}>{row.cost_tier || "—"}</Badge> },
    { key: "latency", header: "latency_tier", label: "latency_tier", render: (row) => <Badge>{row.latency_tier || "—"}</Badge> },
  ];

  return (
    <Card
      title="模型目录"
      subtitle={`GET /api/v1/models · ${filtered.length} / ${all.length} 个模型 (筛选条件写在 URL, 可分享)`}
    >
      <div className="stack">
        <form className="row row--wrap" aria-label="模型目录筛选" data-testid="models-filters" onSubmit={(event) => event.preventDefault()}>
          <div style={{ minWidth: "12rem", flex: "1 1 12rem" }}>
            <SelectField
              label="provider"
              options={[
                { value: ALL, label: "全部 provider" },
                ...providerOptions.map((value) => ({ value, label: value })),
              ]}
              value={providerFilter}
              onChange={(event) => setProviderFilter(event.target.value)}
            />
          </div>
          <div style={{ minWidth: "12rem", flex: "1 1 12rem" }}>
            <SelectField
              label="operation"
              options={[
                { value: ALL, label: "全部 operation" },
                ...operationOptions.map((value) => ({ value, label: value })),
              ]}
              value={operationFilter}
              onChange={(event) => setOperationFilter(event.target.value)}
            />
          </div>
          <div style={{ minWidth: "12rem", flex: "1 1 12rem" }}>
            <SelectField
              label="cost_tier"
              options={[
                { value: ALL, label: "全部 cost_tier" },
                ...costTierOptions.map((value) => ({ value, label: value })),
              ]}
              value={costTierFilter}
              onChange={(event) => setCostTierFilter(event.target.value)}
            />
          </div>
        </form>

        <QueryState
          query={models}
          isEmpty={() => filtered.length === 0}
          empty={
            <p className="small muted">
              {all.length === 0
                ? "模型目录为空: Provider 未注册任何模型描述符 (model catalog 由后端按 Provider 实现与配置生成)。"
                : "当前筛选条件下没有模型。放宽筛选或点击筛选项选择\"全部\"。"}
            </p>
          }
        >
          {() => (
            <div data-testid="models-table">
              <Table
                ariaLabel="模型目录"
                columns={columns}
                rows={filtered}
                rowKey={(row) => `${row.provider_id}|${row.model_id}`}
              />
            </div>
          )}
        </QueryState>
      </div>
    </Card>
  );
}

/** 制品表: 生成的音视频/图片制品元数据 + 删除 (二次确认, 不可恢复)。 */
function ArtifactsSection() {
  const artifacts = useArtifacts();
  const remove = useDeleteArtifact();
  const [pendingDelete, setPendingDelete] = useState<ArtifactMeta | null>(null);
  const nowSeconds = useNowSeconds();

  const columns: Array<Column<ArtifactMeta>> = [
    {
      key: "artifact_id",
      header: "artifact_id",
      label: "artifact_id",
      render: (row) => (
        <span className="row row--tight">
          <ShortId value={row.artifact_id} />
          <CopyButton value={row.artifact_id} label="复制 artifact_id" />
        </span>
      ),
    },
    { key: "kind", header: "kind", label: "kind", render: (row) => <Badge tone="info">{row.kind}</Badge> },
    { key: "mime", header: "mime", label: "mime", render: (row) => <code className="code-inline">{row.mime_type}</code> },
    { key: "size", header: "大小", label: "大小", align: "right", render: (row) => <span className="tabular">{formatBytes(row.size_bytes)}</span> },
    {
      key: "duration",
      header: "时长",
      label: "时长",
      align: "right",
      render: (row) => <span className="tabular">{row.duration_seconds !== null ? formatDuration(row.duration_seconds) : "—"}</span>,
    },
    { key: "created", header: "创建时间", label: "创建时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
    {
      key: "expires",
      header: "过期时间",
      label: "过期时间",
      render: (row) => {
        const expired = row.expires_at > 0 && row.expires_at < nowSeconds;
        return (
          <span className="row row--tight nowrap">
            <span style={expired ? { color: "var(--color-danger)" } : undefined}>
              {row.expires_at > 0 ? formatTimestamp(row.expires_at) : "—"}
            </span>
            {expired ? <Badge tone="danger">已过期</Badge> : null}
          </span>
        );
      },
    },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button
          variant="ghost"
          size="sm"
          disabled={remove.isPending}
          onClick={() => setPendingDelete(row)}
          accessibleName={`删除制品 ${row.artifact_id}`}
        >
          删除
        </Button>
      ),
    },
  ];

  return (
    <Card title="制品 (Artifacts)" subtitle="GET /api/v1/artifacts · TTS / 图片 / 视频等生成制品的元数据与生命周期">
      <QueryState
        query={artifacts}
        isEmpty={(data) => data.artifacts.length === 0}
        empty={<p className="small muted">暂无制品记录 (Agent 生成语音 / 图片 / 视频后会出现在这里)。</p>}
      >
        {(data) => (
          <div data-testid="artifacts-table">
            <Table ariaLabel="制品列表" columns={columns} rows={data.artifacts} rowKey={(row) => row.artifact_id} />
          </div>
        )}
      </QueryState>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="删除制品"
        tone="danger"
        impact={
          pendingDelete ? (
            <span>
              将删除制品 <code className="code-inline">{pendingDelete.artifact_id}</code> ({pendingDelete.kind},{" "}
              {formatBytes(pendingDelete.size_bytes)})。文件与元数据一并移除, <strong>不可恢复</strong>;
              引用它的历史消息将失去附件。
            </span>
          ) : (
            ""
          )
        }
        confirmLabel="删除制品"
        loading={remove.isPending}
        onConfirm={() => {
          if (!pendingDelete) return;
          remove.mutate(pendingDelete.artifact_id, { onSuccess: () => setPendingDelete(null) });
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </Card>
  );
}

/**
 * Providers & Models 域 (§8.1 IA 第 4 行)。
 *
 * 三段: Provider 列表 (连通性测试写审计) / 模型目录 (URL 筛选) / 制品 (删除二次确认)。
 * 全部数据来自真实端点; 子系统未启用或 scope 不足由 QueryState 渲染对应状态。
 */
export default function ProvidersPage() {
  return (
    <div className="stack stack--loose">
      <PageHeader
        title="Providers & Models"
        description="Provider 健康、模型能力、模态、限制、成本/延迟层级"
      />
      <ProvidersSection />
      <ModelsSection />
      <ArtifactsSection />
    </div>
  );
}
