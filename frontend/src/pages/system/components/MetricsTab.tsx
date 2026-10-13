import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getPrometheusText } from "@/api/system";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { CodeBlock } from "@/components/DataDisplay";
import { CopyButton } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { ErrorState } from "@/components/StateViews";
import { Table, type Column } from "@/components/Table";
import { useMetricsSnapshot } from "@/hooks/queries";
import { formatInt } from "@/lib/format";

interface NameValue {
  name: string;
  value: number;
}

interface HistogramRow {
  name: string;
  count: number;
  sum: number;
}

const SORTED = (rows: NameValue[]) => [...rows].sort((a, b) => a.name.localeCompare(b.name));

/**
 * 指标 tab: /metrics 快照 (counters / gauges / histograms) + Prometheus 文本。
 * Prometheus 文本按需拉取 (可能很大, 不随页面自动加载)。
 */
export default function MetricsTab() {
  const metrics = useMetricsSnapshot();
  const [promEnabled, setPromEnabled] = useState(false);
  const prom = useQuery({
    queryKey: ["system", "prometheus-text"],
    queryFn: () => getPrometheusText(),
    enabled: promEnabled,
    staleTime: 30_000,
    retry: false,
  });

  const counterColumns: Array<Column<NameValue>> = [
    { key: "name", header: "counter", label: "counter", render: (row) => <code className="code-inline">{row.name}</code> },
    { key: "value", header: "值", label: "值", align: "right", render: (row) => <span className="tabular">{formatInt(row.value)}</span> },
  ];

  const histogramColumns: Array<Column<HistogramRow>> = [
    { key: "name", header: "histogram", label: "histogram", render: (row) => <code className="code-inline">{row.name}</code> },
    { key: "count", header: "count", label: "count", align: "right", render: (row) => <span className="tabular">{formatInt(row.count)}</span> },
    { key: "sum", header: "sum", label: "sum", align: "right", render: (row) => <span className="tabular">{row.sum}</span> },
    {
      key: "avg",
      header: "均值 (sum/count)",
      label: "均值",
      align: "right",
      render: (row) => <span className="tabular">{row.count > 0 ? (row.sum / row.count).toFixed(2) : "—"}</span>,
    },
  ];

  return (
    <div className="stack" data-testid="system-metrics">
      <QueryState query={metrics}>
        {(data) => {
          const counters = SORTED(Object.entries(data.counters).map(([name, value]) => ({ name, value })));
          const gauges = SORTED(Object.entries(data.gauges).map(([name, value]) => ({ name, value })));
          const histograms = Object.entries(data.histograms)
            .map(([name, item]) => ({ name, count: item.count, sum: item.sum }))
            .sort((a, b) => a.name.localeCompare(b.name));

          return (
            <div className="stack stack--loose">
              <Card title="Counters" subtitle={`累计计数 · ${counters.length} 项`}>
                {counters.length === 0 ? (
                  <p className="small muted">暂无 counter 指标。</p>
                ) : (
                  <div data-testid="metrics-counters-table">
                    <Table ariaLabel="Counter 指标" compact columns={counterColumns} rows={counters} rowKey={(row) => row.name} />
                  </div>
                )}
              </Card>

              <Card title="Gauges" subtitle={`瞬时值 · ${gauges.length} 项`}>
                {gauges.length === 0 ? (
                  <p className="small muted">暂无 gauge 指标。</p>
                ) : (
                  <div data-testid="metrics-gauges-table">
                    <Table ariaLabel="Gauge 指标" compact columns={counterColumns} rows={gauges} rowKey={(row) => row.name} />
                  </div>
                )}
              </Card>

              <Card title="Histograms" subtitle={`分布 (count / sum) · ${histograms.length} 项`}>
                {histograms.length === 0 ? (
                  <p className="small muted">暂无 histogram 指标。</p>
                ) : (
                  <div data-testid="metrics-histograms-table">
                    <Table ariaLabel="Histogram 指标" compact columns={histogramColumns} rows={histograms} rowKey={(row) => row.name} />
                  </div>
                )}
              </Card>
            </div>
          );
        }}
      </QueryState>

      <Card
        title="Prometheus 文本 (/metrics)"
        subtitle="按需拉取; metrics_auth_enabled=true 时该端点也需要认证"
        actions={
          <div className="row row--tight">
            {prom.data ? <CopyButton value={prom.data} label="复制 Prometheus 文本" /> : null}
            <Button
              variant="secondary"
              size="sm"
              data-testid="metrics-prometheus-load"
              onClick={() => (promEnabled ? void prom.refetch() : setPromEnabled(true))}
              loading={prom.isFetching}
            >
              {promEnabled ? "刷新" : "拉取"}
            </Button>
          </div>
        }
      >
        {prom.isError ? (
          <ErrorState
            title="Prometheus 文本拉取失败"
            description={prom.error instanceof Error ? prom.error.message : String(prom.error)}
            onRetry={() => void prom.refetch()}
            retrying={prom.isFetching}
          />
        ) : prom.data ? (
          <CodeBlock ariaLabel="Prometheus 文本指标" maxHeight="28rem">
            {prom.data}
          </CodeBlock>
        ) : (
          <p className="small muted">尚未拉取。文本可能较大, 点击"拉取"后加载。</p>
        )}
      </Card>
    </div>
  );
}
