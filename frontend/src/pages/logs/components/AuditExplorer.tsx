import { useState, type FormEvent } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { TextField } from "@/components/Form";
import { QueryState } from "@/components/QueryState";
import { Table, type Column } from "@/components/Table";
import { useAudit } from "@/hooks/queries";
import { useUrlNumber, useUrlString } from "@/hooks/useUrlState";
import { downloadCsv } from "@/lib/csv";
import { formatTimestamp, truncate } from "@/lib/format";
import type { AuditEntry } from "@/api/types";

const LIMITS = [50, 100, 200, 500];

/** 状态码 → 徽标语调 (文本同时显示数字, 不只靠颜色)。 */
function statusTone(code: number): "success" | "warning" | "danger" | "neutral" {
  if (code >= 500) return "danger";
  if (code >= 400) return "warning";
  if (code >= 200 && code < 300) return "success";
  return "neutral";
}

interface AuditFilterDraft {
  action: string;
  actor: string;
  prefix: string;
  limit: string;
}

const EMPTY_DRAFT: AuditFilterDraft = { action: "", actor: "", prefix: "", limit: "100" };

/**
 * 过滤表单 (草稿态): 提交才写回 URL, 避免每次按键打一次后端 (审计表可能很大)。
 * 父级以 key=当前 URL 值挂载 —— URL 被外部改动 (提交 / 重置 / 回退 / 分享链接)
 * 时重挂载并以新值初始化草稿 (React "以 key 重置状态"模式, 不在 effect 里 setState)。
 */
function AuditFilterForm({
  initial,
  onApply,
}: {
  initial: AuditFilterDraft;
  onApply: (next: AuditFilterDraft) => void;
}) {
  const [draft, setDraft] = useState<AuditFilterDraft>(initial);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const parsed = Number(draft.limit);
    onApply({
      ...draft,
      limit: String(Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, 1000) : 100),
    });
  };

  return (
    <form className="row row--wrap" onSubmit={onSubmit} data-testid="audit-filters" aria-label="审计过滤条件">
      <div style={{ minWidth: "12rem", flex: "1 1 12rem" }}>
        <TextField
          label="action"
          value={draft.action}
          onChange={(event) => setDraft({ ...draft, action: event.target.value })}
          placeholder="如 config.patch"
        />
      </div>
      <div style={{ minWidth: "12rem", flex: "1 1 12rem" }}>
        <TextField
          label="actor"
          value={draft.actor}
          onChange={(event) => setDraft({ ...draft, actor: event.target.value })}
          placeholder="如 session / token:abc"
        />
      </div>
      <div style={{ minWidth: "14rem", flex: "1 1 14rem" }}>
        <TextField
          label="path_prefix"
          value={draft.prefix}
          onChange={(event) => setDraft({ ...draft, prefix: event.target.value })}
          placeholder="/api/v1/agents"
        />
      </div>
      <div style={{ minWidth: "8rem" }}>
        <TextField
          label="limit"
          type="number"
          min={1}
          max={1000}
          value={draft.limit}
          onChange={(event) => setDraft({ ...draft, limit: event.target.value })}
        />
      </div>
      <div className="row row--tight" style={{ alignSelf: "flex-end" }}>
        <Button type="submit" variant="primary" data-testid="audit-search">
          查询
        </Button>
        <Button type="button" variant="ghost" onClick={() => onApply(EMPTY_DRAFT)}>
          重置
        </Button>
      </div>
    </form>
  );
}

/**
 * 审计浏览器 (GET /api/v1/audit)。
 *
 * - 过滤条件写进 URL (action / actor / prefix / limit), 可分享可回退;
 * - 表单提交才改 URL, 避免每次按键打一次后端 (审计表可能很大);
 * - tokens[] 模式下 `/audit` 要求 `"*"` 通配 scope, 403 由 <QueryState> 渲染
 *   permission-denied 并说明所需 scope, 不静默显示空表 (§8.5)。
 */
export function AuditExplorer() {
  const [action, setAction] = useUrlString("action");
  const [actor, setActor] = useUrlString("actor");
  const [prefix, setPrefix] = useUrlString("prefix");
  const [limit, setLimit] = useUrlNumber("limit", 100);

  const query = useAudit({
    action: action || undefined,
    actor: actor || undefined,
    path_prefix: prefix || undefined,
    limit,
  });

  const onApply = (next: AuditFilterDraft) => {
    setAction(next.action.trim());
    setActor(next.actor.trim());
    setPrefix(next.prefix.trim());
    const parsed = Number(next.limit);
    setLimit(Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, 1000) : 100);
  };

  const columns: Array<Column<AuditEntry>> = [
    {
      key: "timestamp",
      header: "时间",
      render: (row) => <span title={row.iso}>{formatTimestamp(row.timestamp)}</span>,
    },
    { key: "actor", header: "执行者", render: (row) => row.actor || <span className="muted">—</span> },
    {
      key: "method",
      header: "方法",
      render: (row) => <code className="code-inline">{row.method}</code>,
    },
    { key: "path", header: "路径", render: (row) => <span title={row.path}>{truncate(row.path, 48)}</span> },
    { key: "action", header: "动作", render: (row) => row.action || <span className="muted">—</span> },
    { key: "target", header: "目标", render: (row) => truncate(row.target || "—", 28) },
    {
      key: "status_code",
      header: "状态",
      align: "right",
      render: (row) => <Badge tone={statusTone(row.status_code)}>{row.status_code}</Badge>,
    },
    {
      key: "detail",
      header: "详情",
      render: (row) => <span className="muted" title={row.detail}>{truncate(row.detail || "—", 40)}</span>,
    },
  ];

  const exportCsv = (rows: readonly AuditEntry[]) => {
    downloadCsv(
      `isac-audit-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.csv`,
      ["timestamp", "iso", "actor", "method", "path", "action", "target", "status_code", "detail"],
      rows as unknown as Array<Record<string, unknown>>,
    );
  };

  return (
    <div className="stack">
      <Callout tone="info" title="scope 口径">
        <span className="small">
          tokens[] 模式下 <code className="code-inline">/api/v1/audit</code> 与{" "}
          <code className="code-inline">/api/v1/logs/tail</code> 都要求{" "}
          <code className="code-inline">"*"</code> 通配 scope (审计与系统日志属最敏感数据面)。
          窄 scope token 会得到 403 <code className="code-inline">SCOPE_FORBIDDEN</code>,
          页面显示"权限不足"而不是空表。
        </span>
      </Callout>

      <AuditFilterForm
        key={`${action}|${actor}|${prefix}|${limit}`}
        initial={{ action, actor, prefix, limit: String(limit) }}
        onApply={onApply}
      />

      <QueryState<AuditEntry[]>
        query={query}
        isEmpty={(rows) => rows.length === 0}
        empty={
          <span>
            当前过滤条件下没有审计记录。审计只记录<strong>控制面写操作与敏感读</strong>,
            普通业务请求不入审计。
          </span>
        }
      >
        {(rows) => (
          <div className="stack stack--tight">
            <div className="row row--between">
              <span className="small muted">
                {rows.length} 条 (最新到最旧, 上限受 limit={limit} 约束)
              </span>
              <Button variant="secondary" size="sm" onClick={() => exportCsv(rows)} data-testid="audit-export">
                导出 CSV
              </Button>
            </div>
            <Table
              columns={columns}
              rows={rows}
              rowKey={(row, index) => `${row.timestamp}-${row.path}-${index}`}
              ariaLabel="审计记录"
              compact
              responsive
            />
          </div>
        )}
      </QueryState>

      <p className="xs muted">
        limit 可选 {LIMITS.join(" / ")} (后端上限 1000)。过滤为服务端执行, 前端不做二次筛选。
      </p>
    </div>
  );
}
