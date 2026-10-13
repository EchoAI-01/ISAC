/** Usage 域的 URL 状态 (筛选/时间范围全部可分享、刷新不丢)。
 *
 * 页面与三个 tab 各自调用本 hook —— URL 是唯一事实源, 多实例读到的值一致。
 * `now` 来自 useNowSeconds() (30s 粒度量化, 渲染安全): 同粒度窗口内
 * query key 稳定, 用量查询最多每 30s 刷新一次。
 */

import { useUrlEnum, useUrlNumber, useUrlString } from "@/hooks/useUrlState";
import { useNowSeconds } from "@/lib/time";
import type { UsageFilter } from "@/api/usage";
import type { UsageGroupBy } from "@/api/types";

export type TimeRange = "1h" | "24h" | "7d" | "30d" | "custom";

export const RANGE_OPTIONS: TimeRange[] = ["1h", "24h", "7d", "30d", "custom"];

export const RANGE_SECONDS: Record<Exclude<TimeRange, "custom">, number> = {
  "1h": 3600,
  "24h": 86400,
  "7d": 7 * 86400,
  "30d": 30 * 86400,
};

/** 汇总维度全集 (后端白名单同序)。 */
export const GROUP_BY_DIMS: UsageGroupBy[] = [
  "provider",
  "model",
  "agent_id",
  "session_id",
  "modality",
  "operation",
  "status",
  "fallback",
];

export interface UsageUrlState {
  range: TimeRange;
  setRange: (next: TimeRange) => void;
  /** epoch 秒 (custom 时来自 URL from/to, 缺省回落近 24h)。 */
  from: number;
  to: number;
  setCustomFrom: (sec: number) => void;
  setCustomTo: (sec: number) => void;
  provider: string;
  model: string;
  agent: string;
  modality: string;
  status: string;
  /** 五个文本筛选统一提交 (表单草稿 → URL)。 */
  applyTextFilters: (next: { provider: string; model: string; agent: string; modality: string; status: string }) => void;
  /** 传给 usage API 的公共过滤参数。 */
  filter: UsageFilter;
  describeRange: string;
}

export function useUsageUrlState(): UsageUrlState {
  const [range, setRange] = useUrlEnum<TimeRange>("range", RANGE_OPTIONS, "24h");
  const [fromParam, setFromParam] = useUrlNumber("from", 0);
  const [toParam, setToParam] = useUrlNumber("to", 0);
  const [provider, setProvider] = useUrlString("provider");
  const [model, setModel] = useUrlString("model");
  const [agent, setAgent] = useUrlString("agent");
  const [modality, setModality] = useUrlString("modality");
  const [status, setStatus] = useUrlString("status");

  const now = useNowSeconds();
  const from =
    range === "custom" ? (fromParam > 0 ? fromParam : now - RANGE_SECONDS["24h"]) : now - RANGE_SECONDS[range];
  const to = range === "custom" && toParam > 0 ? toParam : now;

  return {
    range,
    setRange,
    from,
    to,
    setCustomFrom: setFromParam,
    setCustomTo: setToParam,
    provider,
    model,
    agent,
    modality,
    status,
    applyTextFilters: (next) => {
      setProvider(next.provider.trim());
      setModel(next.model.trim());
      setAgent(next.agent.trim());
      setModality(next.modality.trim());
      setStatus(next.status.trim());
    },
    filter: {
      from,
      to,
      provider: provider || undefined,
      model: model || undefined,
      agent_id: agent || undefined,
      modality: modality || undefined,
      status: status || undefined,
    },
    describeRange: range === "custom" ? "自定义范围" : `近 ${range}`,
  };
}

/** epoch 秒 → `<input type="datetime-local">` 值 (浏览器本地时区)。
 *
 * 这是表单态构造, 不是展示格式化 (展示一律走 lib/format 的 format*)。 */
export function toLocalInputValue(sec: number): string {
  const date = new Date(sec * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** datetime-local 值 → epoch 秒 (非法输入返回 null)。 */
export function fromLocalInputValue(value: string): number | null {
  if (value === "") return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}
