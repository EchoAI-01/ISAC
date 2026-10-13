import { useState } from "react";

import { Callout, Card } from "@/components/Card";
import { SegmentedControl } from "@/components/Inputs";
import { readTheme, resolveTheme, saveTheme, type ThemePreference } from "@/lib/theme";

const OPTIONS: Array<{ value: ThemePreference; label: string }> = [
  { value: "auto", label: "跟随系统" },
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
];

/**
 * 外观 tab: 主题偏好 (auto / light / dark)。
 *
 * 偏好存 localStorage (isac.console.theme) —— 仅非敏感 UI 偏好,
 * 与凭据严格分离 (SPEC §8.2 规则 4)。auto 时由 theme.ts 解析系统偏好
 * 写入 data-theme, 系统切换由 AppShell 的 watchSystemTheme 跟随。
 */
export default function AppearanceTab() {
  const [preference, setPreference] = useState<ThemePreference>(() => readTheme());

  return (
    <div className="stack" data-testid="system-appearance">
      <Card title="主题" subtitle="偏好只影响本浏览器 (localStorage), 不写入服务端配置">
        <div className="stack">
          <div className="row row--tight">
            <span className="toolbar__label" id="theme-preference-label">
              主题偏好
            </span>
            <SegmentedControl
              ariaLabel="主题偏好"
              options={OPTIONS}
              value={preference}
              onChange={(next) => {
                const value = next as ThemePreference;
                setPreference(value);
                saveTheme(value); // 内部同时 applyTheme (写 data-theme)
              }}
            />
          </div>
          <p className="small muted">
            当前生效: <strong>{resolveTheme(preference)}</strong>
            {preference === "auto" ? " (跟随系统, 系统切换主题时自动跟随)" : ""}。
          </p>
        </div>
      </Card>

      <Callout tone="info" title="存储边界">
        <span className="small">
          localStorage 里只有这一个 UI 偏好键; 管理 Token 走 sessionStorage / 内存,
          Provider 密钥只在服务端 —— 浏览器存储中没有任何凭据 (§8.2 规则 4)。
        </span>
      </Callout>
    </div>
  );
}
