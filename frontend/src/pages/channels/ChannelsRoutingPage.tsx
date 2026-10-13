import { PageHeader } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { useUrlTab } from "@/hooks/useUrlState";

import ChannelStatusPanel from "./components/ChannelStatusPanel";
import LinksPanel from "./components/LinksPanel";
import RoutingRulesPanel from "./components/RoutingRulesPanel";

const TABS = ["status", "routing", "links"] as const;

/**
 * Channels & Routing 域 (§8.1 IA 第 3 行)。
 *
 * 三个 tab:
 * - Channel 状态: 仅来自 /health.subsystems.channels (/channels* REST 后端未实现,
 *   绑定能力只有 MCP 工具 —— 面板内已向用户明示, 不放假按钮);
 * - 路由规则: bindings + default_agents 本地草稿编辑 → 覆盖式 PUT (提交前预览);
 * - 互联 Link: 列表 / 创建 / 删除 + mesh_role 语义说明。
 */
export default function ChannelsRoutingPage() {
  const [tab, setTab] = useUrlTab(TABS, "status");

  return (
    <div className="stack">
      <PageHeader
        title="Channels & Routing"
        description="连接状态、绑定、默认 Agent、触发词、primary/observer/candidate"
      />

      <Tabs
        ariaLabel="Channels 与路由分区"
        value={tab}
        onChange={setTab}
        items={[
          { value: "status", label: "Channel 状态", content: <ChannelStatusPanel /> },
          { value: "routing", label: "路由规则", content: <RoutingRulesPanel /> },
          { value: "links", label: "互联 Link", content: <LinksPanel /> },
        ]}
      />
    </div>
  );
}
