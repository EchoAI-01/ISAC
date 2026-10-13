import type { MemoryJargon, MemoryProfile } from "@/api/types";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useMemoryJargon, useMemoryProfiles } from "@/hooks/queries";
import { formatTimestamp, truncate } from "@/lib/format";

const timeOrDash = (value: number | null): string => (value === null ? "—" : formatTimestamp(value));

/** 人物画像 tab: GET /memory/{agent}/profiles。 */
export function ProfilesTab({ agentId }: { agentId: string }) {
  const profiles = useMemoryProfiles(agentId);

  const columns: Array<Column<MemoryProfile>> = [
    { key: "person_id", header: "person_id", label: "person_id", render: (row) => <span className="mono small">{row.person_id}</span> },
    { key: "name", header: "称呼", label: "称呼", render: (row) => row.name || "—" },
    {
      key: "profile_text",
      header: "画像",
      label: "画像",
      render: (row) => (
        <span className="small" title={row.profile_text ?? undefined}>
          {row.profile_text ? truncate(row.profile_text, 120) : "—"}
        </span>
      ),
    },
    {
      key: "depth",
      header: "关系深度",
      label: "关系深度",
      align: "right",
      render: (row) => <span className="tabular">{row.relationship_depth ?? "—"}</span>,
    },
    {
      key: "interactions",
      header: "互动次数",
      label: "互动次数",
      align: "right",
      render: (row) => <span className="tabular">{row.interaction_count ?? "—"}</span>,
    },
    { key: "first_seen", header: "首次出现", label: "首次出现", render: (row) => <span className="nowrap">{timeOrDash(row.first_seen)}</span> },
    { key: "last_seen", header: "最近出现", label: "最近出现", render: (row) => <span className="nowrap">{timeOrDash(row.last_seen)}</span> },
  ];

  return (
    <div data-testid="memory-profiles">
      <QueryState
        query={profiles}
        isEmpty={(data) => data.profiles.length === 0}
        empty={<p className="small muted">暂无人物画像 (对话中识别到稳定人物并积累互动后生成)。</p>}
      >
        {(data) => <Table ariaLabel="人物画像列表" columns={columns} rows={data.profiles} rowKey={(row) => row.person_id} />}
      </QueryState>
    </div>
  );
}

/** 行话 tab: GET /memory/{agent}/jargon。 */
export function JargonTab({ agentId }: { agentId: string }) {
  const jargon = useMemoryJargon(agentId);

  const columns: Array<Column<MemoryJargon>> = [
    { key: "word", header: "词", label: "词", render: (row) => <strong>{row.word}</strong> },
    { key: "meaning", header: "含义", label: "含义", render: (row) => <span className="small">{row.meaning || "—"}</span> },
    {
      key: "context",
      header: "语境",
      label: "语境",
      render: (row) => (
        <span className="small muted" title={row.context ?? undefined}>
          {row.context ? truncate(row.context, 100) : "—"}
        </span>
      ),
    },
    {
      key: "usage_count",
      header: "使用次数",
      label: "使用次数",
      align: "right",
      render: (row) => <span className="tabular">{row.usage_count ?? "—"}</span>,
    },
  ];

  return (
    <div data-testid="memory-jargon">
      <QueryState
        query={jargon}
        isEmpty={(data) => data.jargon.length === 0}
        empty={<p className="small muted">暂无行话记录 (圈子黑话 / 特有表达被识别后出现在这里)。</p>}
      >
        {(data) => <Table ariaLabel="行话列表" columns={columns} rows={data.jargon} rowKey={(row, index) => `${row.word}|${index}`} />}
      </QueryState>
    </div>
  );
}
