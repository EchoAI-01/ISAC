import { Callout, PageHeader } from "@/components/Card";
import { SelectField } from "@/components/Form";
import { EmptyState, ErrorBoundaryState } from "@/components/StateViews";
import { Tabs } from "@/components/Tabs";
import { useAgentConfig, useAgents } from "@/hooks/queries";
import { useUrlString, useUrlTab } from "@/hooks/useUrlState";

import EpisodesTab from "./components/EpisodesTab";
import GovernanceTab from "./components/GovernanceTab";
import { JargonTab, ProfilesTab } from "./components/ProfilesJargonTabs";

const TABS = ["episodes", "profiles", "jargon", "governance"] as const;

/**
 * Memory 域 (§8.1 IA 第 7 行)。
 *
 * 记忆按命名空间隔离: 默认 = agent_id (私有), `shared` = 跨 Agent 共享。
 * 页面以"选中的 Agent"为入口 (URL ?agent=), 命名空间来自其 AgentConfig;
 * 选到 shared 命名空间的 Agent 时, 看到的就是所有 shared Agent 共用的数据。
 */
export default function MemoryPage() {
  const [agent, setAgent] = useUrlString("agent");
  const [tab, setTab] = useUrlTab(TABS, "episodes");
  const agents = useAgents();
  const config = useAgentConfig(agent || undefined);

  const namespace = typeof config.data?.memory_namespace === "string" ? config.data.memory_namespace : "";
  const shared = namespace === "shared";

  return (
    <div className="stack" data-testid="memory-page">
      <PageHeader
        title="Memory"
        description="命名空间、Episode、人物画像、行话、索引健康和容量"
      />

      {agents.isError ? (
        <ErrorBoundaryState error={agents.error} onRetry={() => void agents.refetch()} retrying={agents.isFetching} />
      ) : (
        <div className="row row--tight" style={{ flexWrap: "wrap" }}>
          <div style={{ minWidth: "16rem" }}>
            <SelectField
              label="Agent (记忆命名空间入口)"
              options={[
                { value: "", label: agents.isLoading ? "加载 Agent 列表中…" : "选择 Agent…" },
                ...(agents.data ?? []).map((item) => ({ value: item.agent_id, label: item.agent_id })),
                // URL 里的 agent 已不在列表 (被销毁) 时保留选项, 让查询把 404 显式呈现。
                ...(agent !== "" && !(agents.data ?? []).some((item) => item.agent_id === agent)
                  ? [{ value: agent, label: `${agent} (不在当前列表)` }]
                  : []),
              ]}
              value={agent}
              onChange={(event) => setAgent(event.target.value)}
            />
          </div>
        </div>
      )}

      {agent !== "" ? (
        <>
          <Callout tone={shared ? "warning" : "info"} title={shared ? "共享命名空间 (memory_namespace=shared)" : `命名空间: ${namespace || "(读取 AgentConfig 中…)"}`}>
            <span className="small">
              {shared
                ? "该 Agent 使用跨 Agent 共享命名空间: 下方数据与所有 shared Agent 共通, 治理操作会影响全部共享方; 销毁 Agent 时后端拒绝清理共享记忆。"
                : "默认命名空间 = agent_id (私有): 下方数据只属于该 Agent。命名空间在 Agents → 详情 → 配置 → 身份 里修改 (高影响变更)。"}
            </span>
          </Callout>

          <Tabs
            ariaLabel="记忆分区"
            value={tab}
            onChange={setTab}
            items={[
              { value: "episodes", label: "Episode", content: <EpisodesTab agentId={agent} /> },
              { value: "profiles", label: "人物画像", content: <ProfilesTab agentId={agent} /> },
              { value: "jargon", label: "行话", content: <JargonTab agentId={agent} /> },
              { value: "governance", label: "治理", content: <GovernanceTab agentId={agent} /> },
            ]}
          />
        </>
      ) : (
        <EmptyState
          title="选择 Agent 以查看记忆"
          description="记忆按命名空间隔离, 先在上方选择一个 Agent (其命名空间默认 = agent_id; 配置为 shared 的 Agent 共享同一份数据)。选择会写入 URL ?agent=, 可直接分享。"
        />
      )}
    </div>
  );
}
