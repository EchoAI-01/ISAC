import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type BadgeTone = "neutral" | "success" | "danger" | "warning" | "info" | "primary";

export interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  /** 前置状态圆点 (非颜色冗余提示: 文本本身已表达状态, 圆点仅辅助)。 */
  dot?: boolean;
  title?: string;
  className?: string;
}

/** 徽标 (状态/标签)。颜色不是唯一信息载体 —— 文本始终存在 (WCAG 1.4.1)。 */
export function Badge({ tone = "neutral", children, dot = false, title, className }: BadgeProps) {
  return (
    <span className={cn("badge", tone !== "neutral" && `badge--${tone}`, className)} title={title}>
      {dot ? <span className="badge__dot" aria-hidden="true" /> : null}
      {children}
    </span>
  );
}

/** Agent 运行态 → 徽标语调 (统一口径, 各页一致)。 */
export function agentStatusTone(status: string): BadgeTone {
  switch (String(status).toLowerCase()) {
    case "running":
      return "success";
    case "starting":
    case "reloading":
      return "info";
    case "error":
    case "failed":
      return "danger";
    case "stopped":
      return "neutral";
    default:
      return "warning";
  }
}

/** 通用状态词 → 徽标语调 (SubAgent / 工作流 / Provider / 投递结果共用)。 */
export function statusTone(status: string): BadgeTone {
  const value = String(status).toLowerCase();
  if (/(^|[^a-z])(ok|success|succeeded|completed|running|healthy|active|bound|added|subscribed)([^a-z]|$)/.test(value)) {
    return "success";
  }
  if (/(fail|error|denied|rejected|timeout|crash|degraded|lost)/.test(value)) return "danger";
  if (/(pending|waiting|queued|running|unknown|retry|partial|skipped)/.test(value)) return "warning";
  if (/(cancel|abort|stopped|disabled|inactive|not_found|removed|unsubscribed)/.test(value)) return "neutral";
  return "neutral";
}
