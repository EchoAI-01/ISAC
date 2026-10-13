/** 展示层格式化 (时间 / 数字 / Token / 成本 / 字节 / 相对时间)。
 *
 * 约定 (CONTROL_PLANE_SPEC §8.5): 成本与 Token 必须明确单位、时区与"估算"标识,
 * 未知价格不得伪造成本 —— 所有成本格式化对 null/undefined 一律返回 "—"。
 */

/** 后端时间戳口径: 秒级 epoch (float)。个别字段为毫秒, 调用方需先归一。 */
export function formatTimestamp(seconds: number | null | undefined, timeZone?: string): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const ms = seconds * 1000;
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone,
  }).format(date);
}

/** 仅时间 (日志台用), 带毫秒。 */
export function formatClockTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "--:--:--";
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  const ms = String(date.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

/** ISO 日期 (日志导出/审计对齐用)。 */
export function formatIsoDate(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const date = new Date(seconds * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toISOString();
}

/** 相对时间 ("3 分钟前"); now 由调用方注入以便测试确定性。 */
export function formatRelative(seconds: number | null | undefined, nowSeconds: number): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const diff = nowSeconds - seconds;
  const abs = Math.abs(diff);
  const suffix = diff >= 0 ? "前" : "后";
  if (abs < 45) return `${Math.round(abs)} 秒${suffix}`;
  if (abs < 90) return `1 分钟${suffix}`;
  if (abs < 45 * 60) return `${Math.round(abs / 60)} 分钟${suffix}`;
  if (abs < 90 * 60) return `1 小时${suffix}`;
  if (abs < 22 * 3600) return `${Math.round(abs / 3600)} 小时${suffix}`;
  if (abs < 26 * 3600) return `1 天${suffix}`;
  return `${Math.round(abs / 86400)} 天${suffix}`;
}

/** 千分位整数; 非数字返回 "—"。 */
export function formatInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value);
}

/** Token 数 (单位: tokens)。 */
export function formatTokens(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(value)} tok`;
}

/** 估算成本 (单位: USD)。SPEC §8.5: 未知价格不伪造, 一律 "—"。 */
export function formatCost(usd: number | null | undefined, digits = 4): string {
  if (usd === null || usd === undefined || Number.isNaN(usd)) return "—";
  return `$${usd.toFixed(digits)}`;
}

/** 带"估算"标识的成本 (表格列头之外的行内提示)。 */
export function formatEstimatedCost(usd: number | null | undefined): string {
  const base = formatCost(usd);
  return base === "—" ? "—" : `${base} (估算)`;
}

/** 字节 → 人类可读。 */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : 1)} ${units[unit]}`;
}

/** 时长 (秒 → "1h 2m 3s")。 */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/** 截断长 id / 文本, 保留前缀 (完整值放 title 属性由调用方决定)。 */
export function truncate(value: string | null | undefined, max = 12): string {
  if (!value) return "—";
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** 安全转字符串 (null/undefined → "—"), 用于表格单元格。 */
export function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** JSON 美化 (未知结构回显)。 */
export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
