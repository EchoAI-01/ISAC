import { parseCost } from "@/api/usage";
import type { UsageSummaryRow } from "@/api/types";
import { SegmentedControl } from "@/components/Inputs";
import { BarChart } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useUsageTimeseries } from "@/hooks/queries";
import { useUrlEnum } from "@/hooks/useUrlState";
import { formatCost, formatInt, formatTokens } from "@/lib/format";

import { CostCell } from "./UsageSummaryTab";
import { useUsageUrlState } from "../useUsageUrlState";

const BUCKETS = ["hour", "day"] as const;

/**
 * 趋势 tab: GET /usage/models/timeseries (bucket=hour|day, 写 URL)。
 * BarChart 自带文本表格替代; time_bucket 为后端按 bucket 归一的时间标签。
 */
export default function UsageTrendTab() {
  const state = useUsageUrlState();
  const [bucket, setBucket] = useUrlEnum<(typeof BUCKETS)[number]>("bucket", BUCKETS, "hour");

  const timeseries = useUsageTimeseries({ ...state.filter, bucket });

  const columns: Array<Column<UsageSummaryRow>> = [
    { key: "bucket", header: `时间桶 (${bucket})`, label: "时间桶", render: (row) => <span className="mono nowrap">{row.time_bucket ?? "—"}</span> },
    { key: "requests", header: "请求数", label: "请求数", align: "right", render: (row) => <span className="tabular">{formatInt(row.request_count)}</span> },
    { key: "total", header: "total tokens", label: "total tokens", align: "right", render: (row) => <span className="tabular">{row.total_tokens === null ? "—" : formatTokens(row.total_tokens)}</span> },
    { key: "cost", header: "估算成本 (USD)", label: "估算成本 USD", align: "right", render: (row) => <CostCell value={row.estimated_cost_sum} /> },
  ];

  return (
    <div className="stack" data-testid="usage-trend">
      <div className="row row--tight">
        <span className="toolbar__label" id="usage-bucket-label">
          时间桶
        </span>
        <SegmentedControl
          ariaLabel="趋势时间桶粒度"
          options={BUCKETS.map((value) => ({ value, label: value === "hour" ? "按小时" : "按天" }))}
          value={bucket}
          onChange={setBucket}
        />
      </div>

      <QueryState
        query={timeseries}
        isEmpty={(rows) => rows.length === 0}
        empty={<p className="small muted">该范围与筛选下没有趋势数据 (期间没有模型调用, 或计量未启用)。</p>}
      >
        {(rows) => (
          <div className="stack">
            <BarChart
              ariaLabel={`Token 用量趋势 (${bucket} 桶, ${state.describeRange})`}
              rows={rows.map((row) => ({
                label: row.time_bucket ?? "—",
                value: row.total_tokens ?? 0,
                display: `${row.total_tokens === null ? "—" : formatTokens(row.total_tokens)} tokens · ${formatCost(parseCost(row.estimated_cost_sum))}`,
              }))}
            />
            <div data-testid="usage-trend-table">
              <Table
                ariaLabel="用量趋势表 (图表的文本替代)"
                compact
                columns={columns}
                rows={rows}
                rowKey={(row, index) => `${row.time_bucket ?? index}`}
                caption="请求数含重试与回退; 成本为估算值 (USD), 价格未知的桶显示 —。"
              />
            </div>
          </div>
        )}
      </QueryState>
    </div>
  );
}
