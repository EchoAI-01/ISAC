import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import { truncate } from "@/lib/format";

/** 键值对列表 (详情页统一排版; dt/dd 语义便于读屏)。 */
export function KeyValue({
  items,
  className,
}: {
  items: Array<{ term: ReactNode; value: ReactNode }>;
  className?: string;
}) {
  return (
    <dl className={cn("kv", className)}>
      {items.map((item, index) => (
        <div key={index} style={{ display: "contents" }}>
          <dt>{item.term}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 代码块 (JSON / Prometheus 文本 / 日志片段)。 */
export function CodeBlock({
  children,
  maxHeight,
  ariaLabel,
  className,
  testId,
}: {
  children: ReactNode;
  maxHeight?: string;
  ariaLabel: string;
  className?: string;
  testId?: string;
}) {
  return (
    <pre
      className={cn("code-block", className)}
      style={maxHeight ? { maxHeight } : undefined}
      aria-label={ariaLabel}
      tabIndex={0}
      data-testid={testId}
    >
      <code>{children}</code>
    </pre>
  );
}

export type StatTone = "default" | "success" | "warning" | "danger";

export interface StatProps {
  label: ReactNode;
  value: ReactNode;
  meta?: ReactNode;
  tone?: StatTone;
  testId?: string;
}

/** 统计卡 (Dashboard / System 概览)。 */
export function Stat({ label, value, meta, tone = "default", testId }: StatProps) {
  return (
    <div className={cn("stat", tone !== "default" && `stat--${tone}`)} data-testid={testId}>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {meta ? <div className="stat__meta">{meta}</div> : null}
    </div>
  );
}

export function StatGrid({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("stat-grid", className)}>{children}</div>;
}

export interface BarChartRow {
  label: string;
  value: number;
  /** 展示文本 (含单位); 缺省用 value。 */
  display?: string;
}

/**
 * 水平条形图 + **同时提供表格文本** (SPEC §8.5: 图表必须同时提供表格/文本摘要)。
 *
 * 视觉条只是 `aria-hidden` 的装饰, 数值以文本形式出现在每行末尾, 读屏用户
 * 拿到的是完整数据而不是"图形"。
 */
export function BarChart({
  rows,
  ariaLabel,
  formatValue,
  className,
}: {
  rows: BarChartRow[];
  ariaLabel: string;
  formatValue?: (value: number) => string;
  className?: string;
}) {
  const max = rows.reduce((acc, row) => Math.max(acc, row.value), 0);
  const render = formatValue ?? ((value: number) => String(value));
  if (rows.length === 0) {
    return <p className="small muted">暂无可绘制数据。</p>;
  }
  return (
    <div className={cn("stack stack--tight", className)}>
      <div className="bar-chart" role="img" aria-label={ariaLabel}>
        {rows.map((row) => (
          <div className="bar-chart__row" key={row.label}>
            <span className="truncate" title={row.label}>
              {row.label}
            </span>
            <span className="bar-chart__track" aria-hidden="true">
              <span
                className="bar-chart__fill"
                style={{ width: `${max > 0 ? Math.max(2, (row.value / max) * 100) : 0}%`, display: "block" }}
              />
            </span>
            <span className="bar-chart__value">{row.display ?? render(row.value)}</span>
          </div>
        ))}
      </div>
      <table className="table table--compact">
        <caption className="sr-only">{ariaLabel} (文本摘要)</caption>
        <thead>
          <tr>
            <th scope="col">分组</th>
            <th scope="col" className="right">
              数值
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td className="right tabular">{row.display ?? render(row.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export interface TimelineItem {
  time: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  muted?: boolean;
}

/** 时间线 (SubAgent 事件 / 审批留痕 / ProgressEvent)。 */
export function Timeline({ items, ariaLabel }: { items: TimelineItem[]; ariaLabel: string }) {
  if (items.length === 0) return <p className="small muted">暂无事件。</p>;
  return (
    <ol className="timeline" aria-label={ariaLabel}>
      {items.map((item, index) => (
        <li className="timeline__item" key={index}>
          <span className={cn("timeline__marker", item.muted && "timeline__marker--muted")} aria-hidden="true" />
          <div className="stack stack--tight">
            <div className="timeline__time">{item.time}</div>
            <div>{item.title}</div>
            {item.description ? <div className="small muted">{item.description}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

/** 长 id 缩写 (完整值放 title, 鼠标/读屏可得)。 */
export function ShortId({ value, max = 12 }: { value: string | null | undefined; max?: number }) {
  if (!value) return <span className="muted">—</span>;
  return (
    <span className="mono" title={value}>
      {truncate(value, max)}
    </span>
  );
}
