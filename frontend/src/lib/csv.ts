/** CSV 导出 (SPEC §8.1 "导出" 操作; 纯客户端, 不依赖后端导出端点)。 */

function escapeCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  // RFC 4180: 含逗号/引号/换行时用双引号包裹, 内部引号翻倍。
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(columns: string[], rows: Array<Record<string, unknown>>): string {
  const header = columns.map(escapeCell).join(",");
  const body = rows.map((row) => columns.map((column) => escapeCell(row[column])).join(","));
  return [header, ...body].join("\r\n");
}

/** 触发浏览器下载 (Blob + 临时 a[download], 用完即撤)。 */
export function downloadCsv(filename: string, columns: string[], rows: Array<Record<string, unknown>>): void {
  // 前置 BOM 让 Excel 正确识别 UTF-8 中文。
  const blob = new Blob([`\uFEFF${toCsv(columns, rows)}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
