import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface Column<T> {
  /** 唯一列键 (React key + 小屏 data-label 回退)。 */
  key: string;
  header: ReactNode;
  /** 小屏卡片模式的行内标签; 省略时该列在 ≤768px 隐藏。 */
  label?: string;
  render: (row: T, index: number) => ReactNode;
  className?: string;
  align?: "left" | "right";
  /** 表头是否可排序 (由调用方接管点击, 本组件只渲染 aria-sort)。 */
  sort?: "ascending" | "descending" | "none";
  onSort?: () => void;
}

export interface TableProps<T> {
  columns: Array<Column<T>>;
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
  /** 表格可访问名 (WCAG 1.3.1; 无可见 caption 时必填)。 */
  ariaLabel: string;
  caption?: ReactNode;
  empty?: ReactNode;
  compact?: boolean;
  /** ≤768px 切换为摘要卡片列表 (默认开; 窄表可关)。 */
  responsive?: boolean;
  onRowClick?: (row: T) => void;
  className?: string;
}

/**
 * 数据表格。
 *
 * - 表头 `scope="col"`, 行首列不额外加 th (保持 DOM 简单且读屏顺序正确);
 * - 小屏切摘要卡片 (`td[data-label]` + CSS grid), 不做横向挤压 (SPEC §8.5);
 * - 空态由调用方通过 `empty` 提供文案, 组件负责渲染成跨列单元格。
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  ariaLabel,
  caption,
  empty,
  compact = false,
  responsive = true,
  onRowClick,
  className,
}: TableProps<T>) {
  const colSpan = columns.length;

  return (
    <div className="table-wrap">
      <table className={cn("table", compact && "table--compact", responsive && "table--responsive", className)}>
        <caption className="sr-only">{caption ?? ariaLabel}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(column.align === "right" && "right", column.className)}
                aria-sort={column.sort ?? undefined}
              >
                {column.onSort ? (
                  <button type="button" className="btn btn--ghost btn--sm" onClick={column.onSort}>
                    {column.header}
                  </button>
                ) : (
                  column.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={colSpan} className="table__empty">
                {empty ?? "暂无数据"}
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr
                key={rowKey(row, index)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={onRowClick ? "row--clickable" : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    data-label={responsive ? (column.label ?? "") : undefined}
                    className={cn(column.align === "right" && "right", column.className)}
                  >
                    {column.render(row, index)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
