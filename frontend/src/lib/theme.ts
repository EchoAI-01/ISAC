/** 主题偏好 (浅色 / 深色 / 跟随系统)。
 *
 * 只存**非敏感 UI 偏好**, 与凭据严格分离 (SPEC §8.2 规则 4: 浏览器不得把管理
 * Token 或 Provider 密钥写入 localStorage)。
 *
 * "跟随系统" 在这里解析成显式 light/dark 写入 `data-theme`, 使 tokens.css 只需
 * 一份深色调色板 (不用 @media 再重复一遍, 避免两份调色板漂移)。
 */

export type ThemePreference = "auto" | "light" | "dark";

const STORAGE_KEY = "isac.console.theme";

export function readTheme(): ThemePreference {
  if (typeof window === "undefined") return "auto";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" || stored === "auto" ? stored : "auto";
  } catch {
    return "auto";
  }
}

/** 系统是否偏好深色 (无 matchMedia 环境按浅色)。 */
export function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveTheme(preference: ThemePreference): "light" | "dark" {
  if (preference === "auto") return systemPrefersDark() ? "dark" : "light";
  return preference;
}

export function applyTheme(preference: ThemePreference): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", resolveTheme(preference));
}

export function saveTheme(preference: ThemePreference): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // 隐私模式/存储被禁: 只应用到当前文档, 不阻塞。
  }
  applyTheme(preference);
}

/**
 * 订阅系统主题变化 (仅在偏好为 auto 时需要跟随)。
 * 返回取消订阅函数。
 */
export function watchSystemTheme(preference: ThemePreference, onChange: () => void): () => void {
  if (preference !== "auto") return () => undefined;
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const listener = () => onChange();
  query.addEventListener("change", listener);
  return () => query.removeEventListener("change", listener);
}
