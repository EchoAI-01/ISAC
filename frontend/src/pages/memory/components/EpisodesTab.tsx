import { useState } from "react";

import type { MemoryEpisode } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { ShortId } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useMemoryEpisodes } from "@/hooks/queries";
import { formatTimestamp, truncate } from "@/lib/format";

const LIMIT = 100;

/**
 * Episode tab: GET /memory/{agent}/episodes (已过滤软删)。
 * content 默认截断, 行内"展开"查看全文 (本地状态, 不额外请求)。
 */
export default function EpisodesTab({ agentId }: { agentId: string }) {
  const episodes = useMemoryEpisodes(agentId, LIMIT);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const columns: Array<Column<MemoryEpisode>> = [
    { key: "id", header: "id", label: "id", render: (row) => <ShortId value={row.id} /> },
    { key: "session", header: "session", label: "session_id", render: (row) => <ShortId value={row.session_id} /> },
    { key: "user", header: "user", label: "user_id", render: (row) => <span className="mono small">{row.user_id || "—"}</span> },
    {
      key: "content",
      header: "内容",
      label: "内容",
      render: (row) => {
        const open = expanded.has(row.id);
        const long = (row.content || "").length > 80;
        return (
          <div className="stack stack--tight">
            <span className="small">{open || !long ? row.content || "(空)" : truncate(row.content, 80)}</span>
            {long ? (
              <Button variant="ghost" size="sm" onClick={() => toggle(row.id)} accessibleName={`${open ? "收起" : "展开"} Episode ${row.id} 全文`}>
                {open ? "收起" : "展开"}
              </Button>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "importance",
      header: "importance",
      label: "importance",
      align: "right",
      render: (row) =>
        row.importance === null ? (
          "—"
        ) : (
          <Badge tone={row.importance >= 0.7 ? "warning" : "neutral"} title="重要度 (记忆检索排序权重之一)">
            {row.importance}
          </Badge>
        ),
    },
    { key: "created", header: "创建时间", label: "创建时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
  ];

  return (
    <div data-testid="memory-episodes">
      <QueryState
        query={episodes}
        isEmpty={(data) => data.episodes.length === 0}
        empty={<p className="small muted">该命名空间下暂无 Episode 记忆 (对话产生记忆后出现在这里; 已软删的条目在"治理" tab 可见)。</p>}
      >
        {(data) => (
          <Table
            ariaLabel="Episode 记忆列表"
            columns={columns}
            rows={data.episodes}
            rowKey={(row) => row.id}
            caption={`最近 ${LIMIT} 条 (后端按时间倒序返回, 已过滤软删条目)。`}
          />
        )}
      </QueryState>
    </div>
  );
}
