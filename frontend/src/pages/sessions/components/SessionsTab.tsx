import type { SessionDto, SessionMessage } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { ShortId } from "@/components/DataDisplay";
import { SelectField } from "@/components/Form";
import { SegmentedControl } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useAgents, useSessionMessages, useSessions } from "@/hooks/queries";
import { useUrlNumber, useUrlString } from "@/hooks/useUrlState";
import { formatRelative, formatTimestamp, truncate } from "@/lib/format";
import { useNowSeconds } from "@/lib/time";

const MSG_LIMITS = ["50", "100", "200", "500"] as const;

/** 选中会话的消息历史 (端点只支持 limit=最近 N 条, 无 offset)。 */
function SessionMessagesPanel({ sessionId }: { sessionId: string }) {
  const [msgLimit, setMsgLimit] = useUrlNumber("msg_limit", 100);
  const messages = useSessionMessages(sessionId, msgLimit);

  const columns: Array<Column<SessionMessage>> = [
    { key: "memory_id", header: "memory_id", label: "memory_id", render: (row) => <ShortId value={row.memory_id} /> },
    {
      key: "content",
      header: "内容",
      label: "内容",
      render: (row) => (
        <span className="small" title={row.content}>
          {truncate(row.content || "(空)", 160)}
        </span>
      ),
    },
    { key: "created", header: "时间", label: "时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
  ];

  return (
    <Card
      title={
        <span className="row row--tight">
          消息历史 <ShortId value={sessionId} max={16} />
        </span>
      }
      subtitle={`GET /sessions/{id}/messages · 端点按 limit 返回最近 N 条 (无 offset 分页)`}
      actions={
        <SegmentedControl
          ariaLabel="消息条数上限"
          options={MSG_LIMITS.map((value) => ({ value, label: `最近 ${value} 条` }))}
          value={String(msgLimit)}
          onChange={(next) => setMsgLimit(Number(next))}
        />
      }
    >
      <QueryState
        query={messages}
        isEmpty={(data) => data.messages.length === 0}
        empty={<p className="small muted">该会话暂无消息记录。</p>}
      >
        {(data) => (
          <div data-testid="sessions-messages-table">
            <Table ariaLabel="会话消息历史" compact columns={columns} rows={data.messages} rowKey={(row, index) => `${row.memory_id}|${index}`} />
          </div>
        )}
      </QueryState>
    </Card>
  );
}

/**
 * 会话 tab: GET /sessions (+agent 筛选) + 点选查看消息历史。
 * 筛选与选中会话都写 URL (?agent= / ?session=), 刷新与分享不丢。
 */
export default function SessionsTab() {
  const [agentFilter, setAgentFilter] = useUrlString("agent");
  const [selected, setSelected] = useUrlString("session");
  const agents = useAgents();
  const sessions = useSessions(agentFilter || undefined);
  const nowSeconds = useNowSeconds();

  const columns: Array<Column<SessionDto>> = [
    {
      key: "session_id",
      header: "session_id",
      label: "session_id",
      render: (row) => (
        <Button variant="ghost" size="sm" onClick={() => setSelected(row.session_id)} accessibleName={`查看会话 ${row.session_id} 的消息`}>
          <ShortId value={row.session_id} />
        </Button>
      ),
    },
    { key: "agent", header: "agent", label: "agent_id", render: (row) => <span className="mono small">{row.agent_id}</span> },
    { key: "user", header: "user", label: "user_id", render: (row) => <span className="mono small">{row.user_id || "—"}</span> },
    { key: "platform", header: "platform", label: "platform", render: (row) => <code className="code-inline">{row.platform}</code> },
    {
      key: "group",
      header: "群组",
      label: "群组",
      render: (row) =>
        row.is_group ? (
          <span className="row row--tight">
            <Badge tone="info">群聊</Badge>
            <span className="mono small">{row.group_id || "—"}</span>
          </span>
        ) : (
          <Badge>私聊</Badge>
        ),
    },
    { key: "state", header: "state", label: "state", render: (row) => <Badge tone={statusTone(row.state)} dot>{row.state}</Badge> },
    { key: "created", header: "创建", label: "创建时间", render: (row) => <span className="nowrap small">{formatTimestamp(row.created_at)}</span> },
    {
      key: "active",
      header: "最近活跃",
      label: "最近活跃",
      render: (row) => <span className="nowrap small" title={formatTimestamp(row.last_active)}>{formatRelative(row.last_active, nowSeconds)}</span>,
    },
  ];

  return (
    <div className="stack" data-testid="sessions-tab">
      <div className="row row--tight" style={{ flexWrap: "wrap" }}>
        <div style={{ minWidth: "16rem" }}>
          <SelectField
            label="按 Agent 筛选"
            options={[
              { value: "", label: "全部 Agent" },
              ...(agents.data ?? []).map((item) => ({ value: item.agent_id, label: item.agent_id })),
            ]}
            value={agentFilter}
            onChange={(event) => {
              setAgentFilter(event.target.value);
              setSelected("");
            }}
          />
        </div>
      </div>

      <Card title="活跃会话" subtitle="GET /api/v1/sessions · SessionManager 在册会话 (点击 session_id 查看消息历史)">
        <QueryState
          query={sessions}
          isEmpty={(data) => data.sessions.length === 0}
          empty={<p className="small muted">当前没有在册会话 (有消息往来后会话才会建立)。</p>}
        >
          {(data) => (
            <div data-testid="sessions-table">
              <Table ariaLabel="会话列表" compact columns={columns} rows={data.sessions} rowKey={(row) => row.session_id} />
            </div>
          )}
        </QueryState>
      </Card>

      {selected !== "" ? <SessionMessagesPanel sessionId={selected} /> : null}
    </div>
  );
}
