import type { ReactNode } from "react";

import type { ConfigDiffChange } from "@/api/types";
import { cn } from "@/lib/cn";
import { prettyJson } from "@/lib/format";

/** 值的稳定展示形态 (对象走 JSON, 敏感哨兵标注为"未修改")。 */
export function formatDiffValue(value: unknown): string {
  if (value === undefined) return "(未设置)";
  if (value === null) return "null (撤销覆盖)";
  if (typeof value === "string") return value === "" ? '(空串 "")' : value;
  if (typeof value === "object") return prettyJson(value);
  return String(value);
}

export interface DiffTableProps {
  changes: ConfigDiffChange[];
  /** 高影响变更 (需二次确认) 的判定结果, 由 config.highImpactChanges 提供。 */
  isHighImpact?: (change: ConfigDiffChange) => boolean;
  caption?: ReactNode;
  className?: string;
}

/**
 * 结构化 diff 表 (SPEC §8.2 规则 2: 所有写操作显示影响范围和结构化 diff)。
 *
 * 三列 = 字段 / 变更前 / 变更后; 高影响行加标记, 让确认对话框可以只列这些行。
 */
export function DiffTable({ changes, isHighImpact, caption, className }: DiffTableProps) {
  if (changes.length === 0) {
    return (
      <p className="small muted" role="status">
        无字段变更 (提交后 revision 不会前进)。
      </p>
    );
  }
  return (
    <div className="table-wrap">
      <table className={cn("diff", className)}>
        <caption className="sr-only">{caption ?? "配置变更对比"}</caption>
        <thead>
          <tr>
            <th scope="col">字段</th>
            <th scope="col">变更前</th>
            <th scope="col">变更后</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((change) => {
            const impactful = isHighImpact?.(change) ?? false;
            return (
              <tr key={change.field}>
                <th scope="row" className="diff__field">
                  {change.field}
                  {impactful ? (
                    <span className="badge badge--warning" style={{ marginLeft: "var(--space-2)" }}>
                      高影响
                    </span>
                  ) : null}
                </th>
                <td className="diff__before">
                  <span className="diff__value">{formatDiffValue(change.before)}</span>
                </td>
                <td className="diff__after">
                  <span className="diff__value">{formatDiffValue(change.after)}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
