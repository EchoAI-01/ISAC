import { PageHeader } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { useFailedPlugins } from "@/hooks/queries";
import { useUrlTab } from "@/hooks/useUrlState";

import FailedPluginsTab from "./components/FailedPluginsTab";
import MarketplaceTab from "./components/MarketplaceTab";
import McpTab from "./components/McpTab";
import PluginsTab from "./components/PluginsTab";
import WorkflowsTab from "./components/WorkflowsTab";

const TABS = ["plugins", "marketplace", "failed", "mcp", "workflows"] as const;

/**
 * Extensions 域 (§8.1 IA 第 6 行; F4 插件市场验收在"市场"与"失败" tab)。
 *
 * 插件 = 已加载清单 + 热重载/卸载; 市场 = 一键安装 + git/url 安装 +
 * allow_install 未开时的 unavailable 呈现; 失败 = 可重试清单 (进程内不持久化);
 * MCP = 全局配置只读视图 (编辑入口唯一, 在 System 域); 工作流 = 清单 + 启动。
 */
export default function ExtensionsPage() {
  const [tab, setTab] = useUrlTab(TABS, "plugins");
  // 失败数角标: 有失败插件时在 tab 上直接可见 (查询与其他组件共享缓存)。
  const failed = useFailedPlugins();
  const failedCount = failed.data ? Object.keys(failed.data.failures).length : undefined;

  return (
    <div className="stack">
      <PageHeader
        title="Extensions"
        description="插件、MCP Server、工具、命令及 Agent × Channel 启用矩阵"
      />

      <Tabs
        ariaLabel="扩展分区"
        value={tab}
        onChange={setTab}
        items={[
          { value: "plugins", label: "插件", content: <PluginsTab /> },
          { value: "marketplace", label: "市场", content: <MarketplaceTab /> },
          {
            value: "failed",
            label: "失败",
            count: failedCount,
            content: <FailedPluginsTab />,
          },
          { value: "mcp", label: "MCP", content: <McpTab /> },
          { value: "workflows", label: "工作流", content: <WorkflowsTab /> },
        ]}
      />
    </div>
  );
}
