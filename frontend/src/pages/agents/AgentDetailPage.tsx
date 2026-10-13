import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { agentStatusTone, Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card, PageHeader } from "@/components/Card";
import { Timeline } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { ErrorState } from "@/components/StateViews";
import { Tabs } from "@/components/Tabs";
import { useAgentLifecycle } from "@/hooks/mutations";
import { useAgentConfig, useAgents, useMemoryEpisodes, useMemoryJargon, useMemoryProfiles } from "@/hooks/queries";
import { useUrlTab } from "@/hooks/useUrlState";
import { formatTimestamp, truncate } from "@/lib/format";

import AgentConfigEditor from "./components/AgentConfigEditor";
import AgentDestroyDialog from "./components/AgentDestroyDialog";
import AgentSubAgentPanel from "./components/AgentSubAgentPanel";
import PluginMatrixPanel from "./components/PluginMatrixPanel";

const TABS = ["config", "plugins", "subagents", "memory"] as const;

/** 记忆概览 tab: 命名空间说明 + 轻量预览, 完整浏览与治理跳转 Memory 域。 */
function AgentMemoryOverview({ agentId }: { agentId: string }) {
  const config = useAgentConfig(agentId);
  const episodes = useMemoryEpisodes(agentId, 5);
  const profiles = useMemoryProfiles(agentId);
  const jargon = useMemoryJargon(agentId);

  const namespace = typeof config.data?.memory_namespace === "string" ? config.data.memory_namespace : "";
  const shared = namespace === "shared";

  return (
    <div className="stack" data-testid="agent-memory-overview">
      <Callout tone={shared ? "warning" : "info"} title={shared ? "共享命名空间 (memory_namespace=shared)" : `记忆命名空间: ${namespace || "(读取中)"}`}>
        <span className="small">
          {shared
            ? "该 Agent 读写跨 Agent 共享的记忆命名空间: 人物画像 / 行话与所有 shared Agent 共通; 销毁时 keep_memory=false 会被后端拒绝清理共享数据。"
            : "私有命名空间 (默认 = agent_id): 记忆数据只属于该 Agent。"}{" "}
          完整浏览、检索与治理 (冻结 / 保护 / 纠正 / 删除 / 恢复) 在 Memory 域。
        </span>
      </Callout>

      <div className="row" style={{ alignItems: "stretch", flexWrap: "wrap" }}>
        <Card title="人物画像" className="grow" subtitle={profiles.data ? `共 ${profiles.data.profiles.length} 人` : undefined}>
          <QueryState
            query={profiles}
            isEmpty={(data) => data.profiles.length === 0}
            empty={<p className="small muted">暂无人物画像 (对话中识别到稳定人物后生成)。</p>}
          >
            {(data) => (
              <p className="small">
                {data.profiles
                  .slice(0, 5)
                  .map((profile) => profile.name || profile.person_id)
                  .join("、")}
                {data.profiles.length > 5 ? ` 等 ${data.profiles.length} 人` : ""}
              </p>
            )}
          </QueryState>
        </Card>

        <Card title="行话" className="grow" subtitle={jargon.data ? `共 ${jargon.data.jargon.length} 条` : undefined}>
          <QueryState
            query={jargon}
            isEmpty={(data) => data.jargon.length === 0}
            empty={<p className="small muted">暂无行话记录。</p>}
          >
            {(data) => (
              <p className="small">
                {data.jargon
                  .slice(0, 5)
                  .map((item) => item.word)
                  .join("、")}
                {data.jargon.length > 5 ? ` 等 ${data.jargon.length} 条` : ""}
              </p>
            )}
          </QueryState>
        </Card>
      </div>

      <Card title="最近 Episode (最多 5 条)" subtitle="完整列表与分页在 Memory 域">
        <QueryState
          query={episodes}
          isEmpty={(data) => data.episodes.length === 0}
          empty={<p className="small muted">暂无 Episode 记忆。</p>}
        >
          {(data) => (
            <Timeline
              ariaLabel="最近 Episode"
              items={data.episodes.map((episode) => ({
                time: formatTimestamp(episode.created_at),
                title: truncate(episode.content || episode.summary || "(空内容)", 100),
                description: `session ${episode.session_id} · user ${episode.user_id}${
                  episode.importance !== null ? ` · importance ${episode.importance}` : ""
                }`,
              }))}
            />
          )}
        </QueryState>
      </Card>

      <div className="row row--tight">
        <Link className="btn btn--primary" to={`/memory?agent=${encodeURIComponent(agentId)}`}>
          打开 Memory 域 (浏览全部与治理)
        </Link>
      </div>
    </div>
  );
}

/**
 * Agent 详情页 (§8.1 第 2 行 + §8.2 配置编辑事务)。
 *
 * 四个 tab: 配置 (完整事务: 校验 → Diff → 高影响确认 → PATCH If-Match → 409 冲突面板)
 * / 插件矩阵 (覆盖式 PUT) / 子任务 (紧凑清单, 时间线在 Sessions 域) / 记忆概览 (跳 Memory 域)。
 * 配置编辑器按 `agentId:revision` 挂载 —— 提交成功并关闭结果面板后缓存失效,
 * 新 revision 触发重挂载, 基线始终与服务端一致。
 */
export default function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useUrlTab(TABS, "config");
  const [destroyOpen, setDestroyOpen] = useState(false);
  const agents = useAgents();
  const lifecycle = useAgentLifecycle();
  const config = useAgentConfig(agentId);

  if (!agentId) {
    return <ErrorState title="缺少 Agent 标识" description="路由中没有 agent_id 参数, 请从 Agents 列表进入。" />;
  }

  const summary = (agents.data ?? []).find((item) => item.agent_id === agentId);
  const running = summary?.status === "running";

  return (
    <div className="stack">
      <PageHeader
        title={
          <span className="row row--tight">
            <span className="mono">{agentId}</span>
            {summary ? (
              <Badge tone={agentStatusTone(summary.status)} dot>
                {summary.status}
              </Badge>
            ) : null}
          </span>
        }
        description="配置编辑事务 (Schema 校验 + Diff + 二次确认 + If-Match 乐观锁)"
        actions={
          <div className="row row--tight">
            <Link className="btn btn--ghost btn--sm" to="/agents">
              ← 返回列表
            </Link>
            <Button
              variant="secondary"
              size="sm"
              disabled={running || lifecycle.start.isPending}
              loading={lifecycle.start.isPending}
              onClick={() => lifecycle.start.mutate(agentId)}
            >
              启动
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!running || lifecycle.stop.isPending}
              loading={lifecycle.stop.isPending}
              onClick={() => lifecycle.stop.mutate(agentId)}
            >
              停止
            </Button>
            <Button variant="danger" size="sm" data-testid="agent-destroy-open" onClick={() => setDestroyOpen(true)}>
              销毁
            </Button>
          </div>
        }
      />

      <Tabs
        ariaLabel="Agent 详情分区"
        value={tab}
        onChange={setTab}
        items={[
          {
            value: "config",
            label: "配置",
            content: (
              <QueryState query={config}>
                {(data) => (
                  <AgentConfigEditor key={`${agentId}:${data.revision}`} agentId={agentId} initial={data} />
                )}
              </QueryState>
            ),
          },
          {
            value: "plugins",
            label: "插件矩阵",
            content: <PluginMatrixPanel agentId={agentId} />,
          },
          {
            value: "subagents",
            label: "子任务",
            content: <AgentSubAgentPanel agentId={agentId} />,
          },
          {
            value: "memory",
            label: "记忆概览",
            content: <AgentMemoryOverview agentId={agentId} />,
          },
        ]}
      />

      <AgentDestroyDialog
        agentId={destroyOpen ? agentId : null}
        onClose={() => setDestroyOpen(false)}
        onDestroyed={() => navigate("/agents")}
      />
    </div>
  );
}
