import type { PluginActionResult } from "@/api/types";
import { Callout } from "@/components/Card";

/**
 * 插件写操作 (install / reload / retry) 的结果面板。
 *
 * F4 验收要求"安装/重载结果要显示 status 与 sync" —— sync 是
 * agent_id → 已同步工具名列表, 逐 Agent 列出, 不只给个数字。
 */
export default function PluginActionResultPanel({
  result,
  action,
}: {
  result: PluginActionResult | null;
  action: string;
}) {
  if (!result) return null;
  const syncEntries = Object.entries(result.sync ?? {});
  return (
    <Callout tone="success" title={`${action}结果: ${result.status}`} >
      <div className="stack stack--tight small" data-testid="plugin-action-result">
        {syncEntries.length === 0 ? (
          <span>
            未同步到任何运行中 Agent (没有运行中实例, 或该插件不提供工具/命令/注入器)。
          </span>
        ) : (
          <>
            <span>已同步到 {syncEntries.length} 个运行中 Agent (经各自启用矩阵过滤):</span>
            <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {syncEntries.map(([agentId, names]) => (
                <li key={agentId}>
                  <code className="code-inline">{agentId}</code>:{" "}
                  <span className="mono">{names.length > 0 ? names.join(", ") : "(无同步条目)"}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Callout>
  );
}
