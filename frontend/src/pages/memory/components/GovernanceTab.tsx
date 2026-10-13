import { useState } from "react";

import type { MemoryItem } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { ShortId } from "@/components/DataDisplay";
import { TextArea } from "@/components/Form";
import { Pagination } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog, Modal } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useGovernanceAction } from "@/hooks/mutations";
import { useMemoryItems } from "@/hooks/queries";
import { useUrlNumber } from "@/hooks/useUrlState";
import { truncate } from "@/lib/format";

const PAGE_SIZES = [20, 50, 100, 200];

/**
 * 治理 tab: GET /memory/{agent}/items (含软删) + 五种治理操作。
 *
 * 治理端点用 {ok:false, detail} 表达"条目不存在 / 受保护拒绝" (HTTP 仍 200) ——
 * useGovernanceAction 已按 ok 分流 Toast (ok=false 是 warning "未生效" + detail 原文),
 * 页面不重复弹提示。删除是软删 (打 deleted 标记), 可在本列表"恢复"。
 */
export default function GovernanceTab({ agentId }: { agentId: string }) {
  const [limit, setLimit] = useUrlNumber("limit", 50);
  const [offset, setOffset] = useUrlNumber("offset", 0);
  const items = useMemoryItems(agentId, limit, offset);
  const governance = useGovernanceAction(agentId);

  const [correctTarget, setCorrectTarget] = useState<MemoryItem | null>(null);
  const [correctText, setCorrectText] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<MemoryItem | null>(null);

  const act = (action: "freeze" | "protect" | "restore", itemId: string) => {
    governance.mutate({ action, itemId });
  };

  const columns: Array<Column<MemoryItem>> = [
    { key: "id", header: "id", label: "id", render: (row) => <ShortId value={row.id} /> },
    { key: "type", header: "类型", label: "类型", render: (row) => <Badge tone="info">{row.type}</Badge> },
    {
      key: "content",
      header: "内容",
      label: "内容",
      render: (row) => (
        <span className="small" title={row.content}>
          {truncate(row.content || "(空)", 120)}
        </span>
      ),
    },
    {
      key: "marks",
      header: "标记",
      label: "标记",
      render: (row) => (
        <span className="row row--tight" style={{ flexWrap: "wrap" }}>
          {row.frozen ? <Badge tone="info">frozen</Badge> : null}
          {row.protected ? <Badge tone="warning">protected</Badge> : null}
          {row.deleted ? <Badge tone="danger">deleted (软删)</Badge> : null}
          {!row.frozen && !row.protected && !row.deleted ? <span className="muted small">—</span> : null}
        </span>
      ),
    },
    {
      key: "actions",
      header: "治理操作",
      label: "治理操作",
      render: (row) => {
        if (row.deleted) {
          return (
            <Button variant="secondary" size="sm" disabled={governance.isPending} onClick={() => act("restore", row.id)} accessibleName={`恢复记忆条目 ${row.id}`}>
              恢复
            </Button>
          );
        }
        return (
          <div className="row row--tight">
            <Button
              variant="ghost"
              size="sm"
              disabled={governance.isPending || row.frozen === 1}
              onClick={() => act("freeze", row.id)}
              accessibleName={`冻结记忆条目 ${row.id}`}
            >
              冻结
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={governance.isPending || row.protected === 1}
              onClick={() => act("protect", row.id)}
              accessibleName={`保护记忆条目 ${row.id}`}
            >
              保护
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={governance.isPending}
              onClick={() => {
                setCorrectTarget(row);
                setCorrectText(row.content);
              }}
              accessibleName={`纠正记忆条目 ${row.id}`}
            >
              纠正
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={governance.isPending || row.protected === 1}
              title={row.protected === 1 ? "受保护条目会被后端拒绝删除" : undefined}
              onClick={() => setDeleteTarget(row)}
              accessibleName={`删除记忆条目 ${row.id}`}
            >
              删除
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="stack" data-testid="memory-governance">
      <Callout tone="info" title="治理语义">
        <span className="small">
          冻结 = 内容定型不再被改写; 保护 = 拒绝删除; 纠正 = 用新内容整体替换; 删除 ={" "}
          <strong>软删</strong> (打 deleted 标记、退出检索, 本列表仍可见并可恢复)。
          操作结果以后端返回的 <code className="code-inline">ok</code> 为准: ok=false 时提示
          "未生效"并原样显示 detail (例如受保护条目拒绝删除) —— 不是 HTTP 错误, 也不代表成功。
        </span>
      </Callout>

      <QueryState query={items}>
        {(data) => (
          <div className="stack">
            <div data-testid="memory-items-table">
              <Table
                ariaLabel="记忆治理列表 (含软删条目)"
                columns={columns}
                rows={data.items}
                rowKey={(row) => row.id}
                caption={`本页 ${data.items.length} 条 · 后端 count = ${data.count} (ok = ${String(data.ok)})`}
              />
            </div>
            <Pagination
              ariaLabel="记忆治理分页"
              offset={offset}
              limit={limit}
              hasMore={data.items.length === limit}
              pageSizeOptions={PAGE_SIZES}
              onChange={setOffset}
              onPageSizeChange={(size) => {
                setLimit(size);
                setOffset(0);
              }}
            />
          </div>
        )}
      </QueryState>

      <Modal
        open={correctTarget !== null}
        title="纠正记忆条目"
        description="用下方内容整体替换该条目的 content (旧内容不保留副本, 操作会写入审计)。"
        onClose={() => setCorrectTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCorrectTarget(null)} disabled={governance.isPending}>
              取消
            </Button>
            <Button
              variant="primary"
              data-testid="memory-correct-submit"
              disabled={correctTarget === null || governance.isPending}
              loading={governance.isPending}
              onClick={() => {
                if (!correctTarget) return;
                governance.mutate(
                  { action: "correct", itemId: correctTarget.id, content: correctText },
                  { onSuccess: () => setCorrectTarget(null) },
                );
              }}
            >
              提交纠正
            </Button>
          </>
        }
      >
        <TextArea
          label="new_content"
          mono
          rows={6}
          value={correctText}
          onChange={(event) => setCorrectText(event.target.value)}
        />
      </Modal>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除记忆条目 (软删)"
        tone="danger"
        impact={
          deleteTarget ? (
            <span>
              条目 <code className="code-inline">{deleteTarget.id}</code> 将被打上 deleted
              标记: 立即退出记忆检索与画像构建, 但数据仍在库中, 可在本列表"恢复"。受保护
              (protected) 条目会被后端拒绝删除。
            </span>
          ) : (
            ""
          )
        }
        confirmLabel="删除条目"
        loading={governance.isPending}
        onConfirm={() => {
          if (!deleteTarget) return;
          governance.mutate({ action: "delete", itemId: deleteTarget.id }, { onSuccess: () => setDeleteTarget(null) });
        }}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
