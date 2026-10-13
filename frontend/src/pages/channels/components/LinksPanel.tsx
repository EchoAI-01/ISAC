import { useState } from "react";

import type { InterAgentLink } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { CheckboxField, SelectField, TextField } from "@/components/Form";
import { TagInput } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog, Modal } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useAddLink, useRemoveLink } from "@/hooks/mutations";
import { useAgents, useLinks } from "@/hooks/queries";

/** 权限枚举 (SPEC §3.3): notify / handoff / memory_query 走 permissions 门, ask 不经门。 */
const PERMISSION_SUGGESTIONS = ["notify", "handoff", "memory_query"];

/** 表单态: max_context_messages 用字符串承载, 留空 = 交给后端默认值。 */
interface LinkDraft {
  from_agent: string;
  to_agent: string;
  direction: "both" | "oneway";
  enabled: boolean;
  permissions: string[];
  visible_memory_scopes: string[];
  max_context_messages: string;
}

const EMPTY_DRAFT: LinkDraft = {
  from_agent: "",
  to_agent: "",
  direction: "both",
  enabled: true,
  permissions: [],
  visible_memory_scopes: [],
  max_context_messages: "",
};

function PermissionsCell({ permissions }: { permissions: string[] }) {
  if (permissions.length === 0) {
    return (
      <Badge tone="warning" title="permissions 为空: notify/handoff/memory_query 全部拒绝 (deny-by-default), 仅 ask 可用">
        空 (deny-by-default)
      </Badge>
    );
  }
  return (
    <span className="row row--tight" style={{ flexWrap: "wrap" }}>
      {permissions.map((permission) => (
        <Badge key={permission} tone="info">
          {permission}
        </Badge>
      ))}
    </span>
  );
}

function LinkCreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [draft, setDraft] = useState<LinkDraft>(EMPTY_DRAFT);
  const agents = useAgents();
  const addLink = useAddLink();

  const knownIds = (agents.data ?? []).map((agent) => agent.agent_id);
  const from = draft.from_agent.trim();
  const to = draft.to_agent.trim();
  const parsedMax = draft.max_context_messages.trim() === "" ? null : Number(draft.max_context_messages);
  const maxValid = parsedMax === null || (Number.isFinite(parsedMax) && parsedMax >= 0);
  const ok = from !== "" && to !== "" && from !== to && maxValid;

  const submit = () => {
    if (!ok) return;
    addLink.mutate(
      {
        from_agent: from,
        to_agent: to,
        direction: draft.direction,
        enabled: draft.enabled,
        permissions: draft.permissions,
        visible_memory_scopes: draft.visible_memory_scopes,
        ...(parsedMax !== null ? { max_context_messages: parsedMax } : {}),
      },
      {
        onSuccess: () => {
          setDraft(EMPTY_DRAFT);
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      wide
      title="创建互联 Link"
      description="Link 描述两个 Agent 之间允许哪些协作 (notify / handoff / memory_query / ask), 以及 handoff 时可见的记忆范围与携带的上下文条数。"
      onClose={() => {
        setDraft(EMPTY_DRAFT);
        onClose();
      }}
      footer={
        <>
          <Button
            variant="secondary"
            onClick={() => {
              setDraft(EMPTY_DRAFT);
              onClose();
            }}
            disabled={addLink.isPending}
          >
            取消
          </Button>
          <Button
            variant="primary"
            data-testid="links-create-submit"
            onClick={submit}
            disabled={!ok}
            loading={addLink.isPending}
          >
            创建 Link
          </Button>
        </>
      }
    >
      <div className="stack">
        <Callout tone="warning" title="permissions 为空 = deny-by-default">
          <span className="small">
            未勾选任何 permission 时, <code className="code-inline">notify</code> /{" "}
            <code className="code-inline">handoff</code> / <code className="code-inline">memory_query</code>{" "}
            全部被拒绝, 只有 <code className="code-inline">ask</code> 可用 (ask 不经 permissions 门)。
            这是有意的安全默认: 协作能力必须显式授予。
          </span>
        </Callout>

        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="grow" style={{ minWidth: "14rem" }}>
            <TextField
              label="from_agent"
              required
              mono
              hint={knownIds.length > 0 ? `现有 Agent: ${knownIds.join(", ")}` : "发起方 Agent id"}
              value={draft.from_agent}
              onChange={(event) => setDraft({ ...draft, from_agent: event.target.value })}
            />
          </div>
          <div className="grow" style={{ minWidth: "14rem" }}>
            <TextField
              label="to_agent"
              required
              mono
              hint="接收方 Agent id (不能与 from_agent 相同)"
              value={draft.to_agent}
              onChange={(event) => setDraft({ ...draft, to_agent: event.target.value })}
            />
          </div>
        </div>

        <SelectField
          label="direction"
          hint="both = 双向可用; oneway = 仅 from → to 方向生效"
          options={[
            { value: "both", label: "both (双向)" },
            { value: "oneway", label: "oneway (单向)" },
          ]}
          value={draft.direction}
          onChange={(event) => setDraft({ ...draft, direction: event.target.value as "both" | "oneway" })}
        />

        <div>
          <span className="field__label" id="links-permissions-label">
            permissions
          </span>
          <TagInput
            values={draft.permissions}
            onChange={(next) => setDraft({ ...draft, permissions: next })}
            ariaLabel="Link permissions"
            allowWildcard={false}
            suggestions={PERMISSION_SUGGESTIONS}
            placeholder="输入 notify / handoff / memory_query 后回车"
          />
        </div>

        <div>
          <span className="field__label" id="links-scopes-label">
            visible_memory_scopes
          </span>
          <TagInput
            values={draft.visible_memory_scopes}
            onChange={(next) => setDraft({ ...draft, visible_memory_scopes: next })}
            ariaLabel="Link 可见记忆范围"
            placeholder="handoff 时对 to_agent 可见的记忆 scope, 回车添加"
          />
        </div>

        <TextField
          label="max_context_messages"
          type="number"
          min={0}
          mono
          hint="handoff 时携带的上下文消息条数上限; 留空 = 使用后端默认值"
          value={draft.max_context_messages}
          onChange={(event) => setDraft({ ...draft, max_context_messages: event.target.value })}
          error={!maxValid ? "必须是不小于 0 的数字, 或留空使用后端默认值。" : undefined}
        />

        <CheckboxField
          label="enabled"
          hint="取消勾选可先创建但不启用 (协作请求会被拒绝)"
          checked={draft.enabled}
          onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
        />

        {!ok && (from === "" || to === "") ? (
          <p className="small muted">from_agent 与 to_agent 必填。</p>
        ) : !ok && from === to ? (
          <p className="small muted">from_agent 与 to_agent 不能相同 (自环 Link 无意义)。</p>
        ) : null}
      </div>
    </Modal>
  );
}

/**
 * 互联 Link tab: GET /links 列表 + POST /links 创建 + DELETE /links?from_agent&to_agent 删除。
 *
 * mesh_role (primary/observer/candidate) 定义在各 Agent 的 AgentConfig 上, 决定
 * handoff 时谁主导对话 —— 这里只做文字说明, 编辑入口在 Agents 详情页的配置 tab。
 */
export default function LinksPanel() {
  const links = useLinks();
  const removeLink = useRemoveLink();
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<InterAgentLink | null>(null);

  const columns: Array<Column<InterAgentLink>> = [
    {
      key: "from",
      header: "from → to",
      label: "from → to",
      render: (row) => (
        <span className="mono nowrap">
          {row.from_agent} → {row.to_agent}
        </span>
      ),
    },
    { key: "direction", header: "direction", label: "direction", render: (row) => <code className="code-inline">{row.direction}</code> },
    {
      key: "enabled",
      header: "enabled",
      label: "enabled",
      render: (row) => (
        <Badge tone={row.enabled ? "success" : "neutral"} dot>
          {row.enabled ? "启用" : "停用"}
        </Badge>
      ),
    },
    { key: "permissions", header: "permissions", label: "permissions", render: (row) => <PermissionsCell permissions={row.permissions} /> },
    {
      key: "scopes",
      header: "可见记忆范围",
      label: "可见记忆范围",
      render: (row) =>
        row.visible_memory_scopes.length > 0 ? (
          <span className="mono small">{row.visible_memory_scopes.join(", ")}</span>
        ) : (
          "—"
        ),
    },
    { key: "max_context", header: "上下文上限", label: "上下文上限", align: "right", render: (row) => <span className="tabular">{row.max_context_messages}</span> },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button variant="ghost" size="sm" accessibleName={`删除 Link ${row.from_agent} 到 ${row.to_agent}`} onClick={() => setPendingDelete(row)}>
          删除
        </Button>
      ),
    },
  ];

  return (
    <div className="stack">
      <Callout tone="info" title="mesh_role 语义 (值在各 Agent 的 AgentConfig 上)">
        <div className="stack stack--tight small">
          <p style={{ margin: 0 }}>
            <strong>primary</strong>: 网格中的主导 Agent —— handoff 发生后由它接管对话并负责最终回复;
            <strong>observer</strong>: 只读观察者, 可以收到 notify 与查询记忆, 但不接管对话;
            <strong>candidate</strong>: 可被 ask 咨询的候选专家, 给出意见后对话仍由发起方 / primary 继续。
          </p>
          <p style={{ margin: 0 }}>
            mesh_role 在 <em>Agents → 详情 → 配置</em> tab 编辑; 本页的 Link 只决定"哪些 Agent 之间允许协作、允许到什么程度"。
          </p>
        </div>
      </Callout>

      <Card
        title="互联 Link"
        subtitle="GET /api/v1/links · 删除走 DELETE /api/v1/links?from_agent&to_agent"
        actions={
          <Button variant="primary" size="sm" data-testid="links-create-open" onClick={() => setCreateOpen(true)}>
            创建 Link
          </Button>
        }
      >
        <QueryState
          query={links}
          isEmpty={(rows) => rows.length === 0}
          empty={
            <p className="small muted">
              尚未配置任何互联 Link。没有 Link 时, Agent 之间的 notify / handoff / memory_query / ask 协作全部不可用。
            </p>
          }
        >
          {(rows) => (
            <div data-testid="channels-links-table">
              <Table
                ariaLabel="Agent 互联 Link 列表"
                columns={columns}
                rows={rows}
                rowKey={(row) => `${row.from_agent}|${row.to_agent}`}
              />
            </div>
          )}
        </QueryState>
      </Card>

      <LinkCreateModal open={createOpen} onClose={() => setCreateOpen(false)} />

      <ConfirmDialog
        open={pendingDelete !== null}
        title="删除互联 Link"
        tone="danger"
        impact={
          pendingDelete ? (
            <span>
              删除后 <code className="code-inline">{pendingDelete.from_agent}</code> →{" "}
              <code className="code-inline">{pendingDelete.to_agent}</code> 之间的 notify / handoff /
              memory_query / ask 协作立即全部不可用; 进行中的 handoff 不受影响, 但后续无法再发起。可重新创建恢复。
            </span>
          ) : (
            ""
          )
        }
        confirmLabel="删除 Link"
        loading={removeLink.isPending}
        onConfirm={() => {
          if (!pendingDelete) return;
          removeLink.mutate(
            { from: pendingDelete.from_agent, to: pendingDelete.to_agent },
            { onSuccess: () => setPendingDelete(null) },
          );
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
