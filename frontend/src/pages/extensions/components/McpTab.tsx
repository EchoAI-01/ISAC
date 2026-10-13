import { Link } from "react-router-dom";

import { Badge } from "@/components/Badge";
import { Callout, Card } from "@/components/Card";
import { CodeBlock } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { useGlobalConfig } from "@/hooks/queries";
import { prettyJson } from "@/lib/format";

/**
 * MCP tab: 只读展示全局配置里的 mcp.servers。
 *
 * 刻意**不做**第二套全局配置写路径 (契约 §4 Extensions): MCP server 的增删改
 * 属于全局配置编辑事务, 唯一入口在 System 域 (校验 / diff / If-Match / 热应用)。
 * 敏感键在 GET /config/global 已被后端脱敏, 这里可以安全展示。
 */
export default function McpTab() {
  const config = useGlobalConfig();

  return (
    <div className="stack" data-testid="extensions-mcp">
      <Callout tone="info" title="MCP server 配置的唯一编辑入口在 System 域">
        <span className="small">
          本 tab 只读展示 <code className="code-inline">config.mcp.servers</code>。
          增删改请走 <Link to="/system?tab=config&section=mcp">System → 全局配置 → mcp 节</Link>{" "}
          的配置编辑事务 (校验 → Diff → 确认 → PATCH If-Match), 避免两条写路径互相覆盖。
          Agent 侧用哪些 server 由各 AgentConfig 的 <code className="code-inline">mcp_servers</code> 白名单决定
          (Agents → 详情 → 配置 → 能力)。
        </span>
      </Callout>

      <Card
        title="mcp.servers (全局配置节选)"
        subtitle={config.data ? `override revision = ${config.data.revision}` : "GET /api/v1/config/global (敏感键已脱敏)"}
        actions={
          <Link className="btn btn--secondary btn--sm" to="/system?tab=config&section=mcp">
            去 System 域编辑
          </Link>
        }
      >
        <QueryState query={config}>
          {(data) => {
            const mcpSection = (data.config ?? {}).mcp;
            const servers =
              mcpSection !== null && typeof mcpSection === "object" && !Array.isArray(mcpSection)
                ? (mcpSection as Record<string, unknown>).servers
                : undefined;

            if (servers === undefined || servers === null) {
              return (
                <p className="small muted">
                  全局配置中没有 mcp.servers 节 —— 未定义任何 MCP server。在 System 域添加后, Agent 才能在
                  mcp_servers 白名单里引用。
                </p>
              );
            }

            const entries = Array.isArray(servers)
              ? servers.map((item, index) => {
                  const name =
                    item !== null && typeof item === "object" && "name" in item
                      ? String((item as Record<string, unknown>).name)
                      : `#${index + 1}`;
                  return [name, item] as const;
                })
              : Object.entries(servers as Record<string, unknown>);

            if (entries.length === 0) {
              return <p className="small muted">mcp.servers 为空 (未定义任何 MCP server)。</p>;
            }

            return (
              <div className="stack">
                <div className="row row--tight" style={{ flexWrap: "wrap" }}>
                  {entries.map(([name]) => (
                    <Badge key={name} tone="info">
                      {name}
                    </Badge>
                  ))}
                </div>
                <CodeBlock ariaLabel="mcp.servers 配置内容 (脱敏后)" maxHeight="24rem">
                  {prettyJson(servers)}
                </CodeBlock>
              </div>
            );
          }}
        </QueryState>
      </Card>
    </div>
  );
}
