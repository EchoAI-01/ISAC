import { Link } from "react-router-dom";

import { Badge } from "@/components/Badge";
import { Card, Callout } from "@/components/Card";
import { QueryState } from "@/components/QueryState";
import { useHealth } from "@/hooks/queries";

/**
 * Channel 状态 tab。
 *
 * 数据来源仅 /health.subsystems.channels (字符串数组 = 后端已注册的 Channel 平台名)。
 * /channels* REST 端点后端未实现, 平台与 Agent 的绑定/解绑目前只由 MCP 工具
 * channel_bind_agent / channel_unbind_agent 提供 —— 因此本 tab 刻意不提供
 * "绑定"按钮 (点了也不会生效), 并用 Callout 向运维者说明。
 */
export default function ChannelStatusPanel() {
  const health = useHealth();

  return (
    <div className="stack">
      <Callout tone="info" title="/channels* REST 端点后端未实现">
        <div className="stack">
          <p>
            Channel 状态目前只能从 <code className="code-inline">/health</code> 的聚合字段{" "}
            <code className="code-inline">subsystems.channels</code> 读取 (已注册的平台名列表);
            后端未提供各平台的独立连接明细 (在线 / 离线 / 错误), 本页不伪造这些数据。
          </p>
          <p>
            平台与 Agent 的绑定 / 解绑能力目前仅由 MCP 工具 <code className="code-inline">channel_bind_agent</code> /{" "}
            <code className="code-inline">channel_unbind_agent</code> 提供, 没有对应的 REST
            端点, 因此这里不提供"绑定"按钮。已生效的绑定规则请看"路由规则"tab (落盘到 data/routing.jsonc)。
          </p>
          <p>
            入站消息的触发词 (trigger_words) 配置在每个 Agent 的 AgentConfig 上, 请在{" "}
            <Link to="/agents">Agents 页面</Link>查看与编辑。
          </p>
        </div>
      </Callout>

      <Card
        title="已注册 Channel 平台"
        subtitle="来源: /health.subsystems.channels · 仅平台名, 无逐平台连接状态"
      >
        <QueryState
          query={health}
          isEmpty={(h) => h.subsystems.channels.length === 0}
          empty={
            <p className="small muted">
              后端当前没有注册任何 Channel 平台 (/health.subsystems.channels 为空)。在配置里注册渠道并重启后才会出现在这里。
            </p>
          }
        >
          {(h) => (
            <div className="stack">
              <div className="row row--tight small muted">
                <span>后端整体健康:</span>
                <Badge tone={h.status === "ok" ? "success" : "warning"} dot>
                  {h.status}
                </Badge>
                <span>· 共 {h.subsystems.channels.length} 个平台已注册</span>
              </div>
              <ul
                className="row row--tight"
                style={{ listStyle: "none", margin: 0, padding: 0, flexWrap: "wrap" }}
                data-testid="channels-list"
              >
                {h.subsystems.channels.map((platform) => (
                  <li key={platform}>
                    <Badge tone="info">{platform}</Badge>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </QueryState>
      </Card>
    </div>
  );
}
