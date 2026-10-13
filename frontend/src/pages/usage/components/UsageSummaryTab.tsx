import { parseCost } from "@/api/usage";
import type { UsageGroupBy, UsageSummaryRow } from "@/api/types";
import { Badge } from "@/components/Badge";
import { BarChart } from "@/components/DataDisplay";
import { CheckboxField } from "@/components/Form";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useUsageSummary } from "@/hooks/queries";
import { useUrlString } from "@/hooks/useUrlState";
import { formatCost, formatInt, formatTokens } from "@/lib/format";

import { GROUP_BY_DIMS, useUsageUrlState } from "../useUsageUrlState";

const tok = (value: number | null | undefined): string => (value === null || value === undefined ? "—" : formatTokens(value));

/** 成本单元格: null = 价格未知, 显示 — 并注明, 不伪造成 0 (SPEC §九 Cost)。 */
export function CostCell({ value }: { value: string | null }) {
  const parsed = parseCost(value);
  if (parsed === null) {
    return (
      <span title="该组存在未命中价目表的调用, 价格未知 (不伪造成 0)">
        — <span className="muted small">(价格未知)</span>
      </span>
    );
  }
  return <span className="tabular">{formatCost(parsed)}</span>;
}

function dimValue(row: UsageSummaryRow, dim: UsageGroupBy): string {
  const value = row[dim];
  if (typeof value === "boolean") return value ? "是" : "否";
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

/**
 * 汇总 tab: GET /usage/models/summary。
 *
 * group_by 可多选 (URL ?group_by=a,b), 表格列随维度动态生成;
 * BarChart 按 Token 排序展示各分组 (自带文本表格替代, 满足 a11y)。
 */
export default function UsageSummaryTab() {
  const state = useUsageUrlState();
  const [groupByParam, setGroupByParam] = useUrlString("group_by");

  const parsedDims = groupByParam
    .split(",")
    .filter((dim): dim is UsageGroupBy => (GROUP_BY_DIMS as string[]).includes(dim));
  const groupBy: UsageGroupBy[] = parsedDims.length > 0 ? parsedDims : ["provider"];

  const summary = useUsageSummary({ ...state.filter, group_by: groupBy });

  const toggleDim = (dim: UsageGroupBy) => {
    const next = groupBy.includes(dim) ? groupBy.filter((item) => item !== dim) : [...groupBy, dim];
    if (next.length === 0) return; // 至少保留一个维度
    setGroupByParam(next.join(","));
  };

  const dimColumns: Array<Column<UsageSummaryRow>> = groupBy.map((dim) => ({
    key: dim,
    header: dim,
    label: dim,
    render: (row) =>
      dim === "fallback" ? (
        <Badge tone={row.fallback ? "warning" : "neutral"}>{dimValue(row, dim)}</Badge>
      ) : (
        <span className="mono small">{dimValue(row, dim)}</span>
      ),
  }));

  const metricColumns: Array<Column<UsageSummaryRow>> = [
    { key: "requests", header: "请求数", label: "请求数", align: "right", render: (row) => <span className="tabular">{formatInt(row.request_count)}</span> },
    { key: "prompt", header: "prompt", label: "prompt tokens", align: "right", render: (row) => <span className="tabular">{tok(row.prompt_tokens)}</span> },
    { key: "completion", header: "completion", label: "completion tokens", align: "right", render: (row) => <span className="tabular">{tok(row.completion_tokens)}</span> },
    { key: "total", header: "total", label: "total tokens", align: "right", render: (row) => <strong className="tabular">{tok(row.total_tokens)}</strong> },
    { key: "cache_read", header: "缓存读", label: "cache read tokens", align: "right", render: (row) => <span className="tabular">{tok(row.cache_read_tokens)}</span> },
    { key: "cache_write", header: "缓存写", label: "cache write tokens", align: "right", render: (row) => <span className="tabular">{tok(row.cache_write_tokens)}</span> },
    { key: "reasoning", header: "推理", label: "reasoning tokens", align: "right", render: (row) => <span className="tabular">{tok(row.reasoning_tokens)}</span> },
    { key: "audio_in", header: "音频入", label: "audio input tokens", align: "right", render: (row) => <span className="tabular">{tok(row.audio_input_tokens)}</span> },
    { key: "audio_out", header: "音频出", label: "audio output tokens", align: "right", render: (row) => <span className="tabular">{tok(row.audio_output_tokens)}</span> },
    { key: "cost", header: "估算成本 (USD)", label: "估算成本 USD", align: "right", render: (row) => <CostCell value={row.estimated_cost_sum} /> },
  ];

  return (
    <div className="stack" data-testid="usage-summary">
      <fieldset className="stack stack--tight" style={{ border: "none", margin: 0, padding: 0 }}>
        <legend className="small muted" style={{ padding: 0 }}>
          group_by 维度 (多选, 写在 URL ?group_by=, 至少保留一个)
        </legend>
        <div className="row row--tight" style={{ flexWrap: "wrap" }}>
          {GROUP_BY_DIMS.map((dim) => (
            <CheckboxField
              key={dim}
              label={dim}
              checked={groupBy.includes(dim)}
              disabled={groupBy.length === 1 && groupBy.includes(dim)}
              onChange={() => toggleDim(dim)}
            />
          ))}
        </div>
      </fieldset>

      <QueryState
        query={summary}
        isEmpty={(rows) => rows.length === 0}
        empty={
          <p className="small muted">
            该范围与筛选下没有用量记录 (期间没有模型调用, 或计量未启用 —— 计量需要 observability.usage.enabled = true)。
          </p>
        }
      >
        {(rows) => (
          <div className="stack">
            <div data-testid="usage-summary-table">
              <Table
                ariaLabel="用量汇总"
                compact
                responsive
                columns={[...dimColumns, ...metricColumns]}
                rows={rows}
                rowKey={(row, index) => `${groupBy.map((dim) => dimValue(row, dim)).join("|")}|${index}`}
                caption="请求数含重试与回退的物理请求; 成本为按 pricing 快照查表的估算值 (USD)。"
              />
            </div>
            <BarChart
              ariaLabel={`各分组 Token 用量 (${state.describeRange})`}
              rows={rows
                .map((row) => ({
                  label: groupBy.map((dim) => dimValue(row, dim)).join(" / "),
                  value: row.total_tokens ?? 0,
                  display: `${tok(row.total_tokens)} tokens · ${formatCost(parseCost(row.estimated_cost_sum))}`,
                }))
                .sort((a, b) => b.value - a.value)}
            />
          </div>
        )}
      </QueryState>
    </div>
  );
}
