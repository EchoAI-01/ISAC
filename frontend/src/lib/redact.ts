/** URL 脱敏 (与后端 `isac/utils/ssrf.py::redact_url` 同语义)。
 *
 * Webhook 订阅 URL 常内嵌凭据 (query token / userinfo), 后端审计与日志已统一脱敏
 * (Fix-109); 前端展示同样必须脱敏 —— 投递与存储仍用原值, 只是不回显给界面。
 */

/** 掩掉 userinfo 与 query/fragment, 保留 scheme/host/port/path。 */
export function redactUrl(raw: string): string {
  if (!raw) return "";
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    // 非绝对 URL: 至少把 query 与 userinfo 形态的片段掩掉。
    return raw.replace(/\?.*$/, "?<redacted>").replace(/\/\/[^/@]*@/, "//<redacted>@");
  }

  const userinfo = url.username || url.password ? "<redacted>@" : "";
  const query = url.search ? "?<redacted>" : "";
  const fragment = url.hash ? "#<redacted>" : "";
  return `${url.protocol}//${userinfo}${url.host}${url.pathname}${query}${fragment}`;
}

/** 判断 URL 是否携带可能被脱敏掉的敏感部分 (用于提示"已脱敏")。 */
export function urlHasSecrets(raw: string): boolean {
  if (!raw) return false;
  try {
    const url = new URL(raw);
    return Boolean(url.username || url.password || url.search);
  } catch {
    return /[?#]/.test(raw) || /\/\/[^/@]*@/.test(raw);
  }
}
