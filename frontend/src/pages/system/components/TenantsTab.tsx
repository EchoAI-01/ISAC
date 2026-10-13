import { useState, type FormEvent } from "react";

import type { TenantDto } from "@/api/types";
import { Badge, statusTone } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { ShortId } from "@/components/DataDisplay";
import { SelectField, TextField } from "@/components/Form";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog, Modal } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useCreateTenant, useDeleteTenant, useTenantMembers } from "@/hooks/mutations";
import { useTenants } from "@/hooks/queries";
import { useUrlString } from "@/hooks/useUrlState";
import { formatTimestamp, prettyJson } from "@/lib/format";

/** members 是 unknown[]: 常见形状 {member_id, member_type} 解析展示, 其余原样 JSON。 */
function memberInfo(member: unknown): { id: string; type: string; raw: boolean } {
  if (typeof member === "string") return { id: member, type: "user", raw: false };
  if (member !== null && typeof member === "object") {
    const record = member as Record<string, unknown>;
    const id = typeof record.member_id === "string" ? record.member_id : typeof record.id === "string" ? record.id : null;
    if (id !== null) {
      return { id, type: typeof record.member_type === "string" ? record.member_type : "user", raw: false };
    }
  }
  return { id: prettyJson(member), type: "user", raw: true };
}

/** 单个租户的成员管理 (展开时挂载, hook 以 tenantId 绑定)。 */
function MembersPanel({ tenant }: { tenant: TenantDto }) {
  const members = useTenantMembers(tenant.tenant_id);
  const [memberId, setMemberId] = useState("");
  const [memberType, setMemberType] = useState("user");

  return (
    <div className="stack" data-testid={`tenant-members-${tenant.tenant_id}`}>
      <div className="row row--tight" style={{ flexWrap: "wrap" }}>
        {tenant.members.length === 0 ? (
          <span className="small muted">暂无成员。</span>
        ) : (
          tenant.members.map((member, index) => {
            const info = memberInfo(member);
            return (
              <span className="row row--tight" key={`${info.id}|${index}`} style={{ alignItems: "center" }}>
                <Badge tone="info" title={info.raw ? "成员条目形状未识别, 显示原始 JSON" : `member_type = ${info.type}`}>
                  {info.raw ? <ShortId value={info.id} max={20} /> : info.id}
                </Badge>
                {!info.raw ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={members.remove.isPending}
                    onClick={() => members.remove.mutate({ memberId: info.id, memberType: info.type })}
                    accessibleName={`把 ${info.id} 移出租户 ${tenant.tenant_id}`}
                  >
                    移出
                  </Button>
                ) : null}
              </span>
            );
          })
        )}
      </div>
      <div className="row row--tight" style={{ flexWrap: "wrap" }}>
        <div style={{ minWidth: "14rem" }}>
          <TextField
            label="member_id"
            mono
            value={memberId}
            onChange={(event) => setMemberId(event.target.value)}
            placeholder="要加入的用户 / Agent ID"
          />
        </div>
        <div style={{ minWidth: "10rem" }}>
          <SelectField
            label="member_type"
            options={[
              { value: "user", label: "user" },
              { value: "agent", label: "agent" },
            ]}
            value={memberType}
            onChange={(event) => setMemberType(event.target.value)}
          />
        </div>
        <Button
          variant="secondary"
          size="sm"
          disabled={memberId.trim() === "" || members.add.isPending}
          loading={members.add.isPending}
          onClick={() => members.add.mutate({ memberId: memberId.trim(), memberType })}
        >
          加入租户
        </Button>
      </div>
    </div>
  );
}

/**
 * 组织筛选表单 (草稿态)。父级以 key=org 挂载: URL 被外部改动 (应用 / 回退 /
 * 分享链接) 时重挂载并以新值初始化草稿 —— 以 key 重置状态, 不在 effect 里 setState。
 */
function OrgFilterForm({
  initial,
  onApply,
  onCreate,
}: {
  initial: string;
  onApply: (next: string) => void;
  onCreate: () => void;
}) {
  const [draft, setDraft] = useState(initial);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    onApply(draft.trim());
  };

  return (
    <form className="row row--tight" onSubmit={onSubmit} aria-label="租户组织筛选" style={{ flexWrap: "wrap" }}>
      <div style={{ minWidth: "16rem" }}>
        <TextField
          label="按 organization_id 筛选"
          mono
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          hint="留空 = 当前身份可见的全部租户; 筛选写在 URL ?org="
        />
      </div>
      <div className="row row--tight" style={{ alignItems: "flex-end" }}>
        <Button variant="secondary" size="sm" type="submit">
          应用
        </Button>
        <Button variant="primary" size="sm" type="button" data-testid="tenants-create-open" onClick={onCreate}>
          创建租户
        </Button>
      </div>
    </form>
  );
}

/**
 * 多租户 tab: 列表 / 创建 / 删除 (requireText) / 成员增删。
 *
 * 权限口径: 绑定租户的 token 只能看到自己的租户 (列表自动收窄),
 * 且用它创建租户恒 403 TENANT_FORBIDDEN —— 由 QueryState / Toast 原样呈现。
 */
export default function TenantsTab() {
  const [org, setOrg] = useUrlString("org");

  const tenants = useTenants(org || undefined);
  const create = useCreateTenant();
  const remove = useDeleteTenant();

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState({ tenant_id: "", organization_id: "", display_name: "" });
  const [pendingDelete, setPendingDelete] = useState<TenantDto | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const columns: Array<Column<TenantDto>> = [
    { key: "tenant_id", header: "tenant_id", label: "tenant_id", render: (row) => <code className="code-inline">{row.tenant_id}</code> },
    { key: "org", header: "organization_id", label: "organization_id", render: (row) => <span className="mono small">{row.organization_id || "—"}</span> },
    { key: "name", header: "显示名", label: "显示名", render: (row) => row.display_name || "—" },
    { key: "state", header: "状态", label: "状态", render: (row) => <Badge tone={statusTone(row.state)} dot>{row.state}</Badge> },
    { key: "created", header: "创建时间", label: "创建时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
    { key: "members", header: "成员", label: "成员数", align: "right", render: (row) => <span className="tabular">{row.members.length}</span> },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <div className="row row--tight">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((current) => (current === row.tenant_id ? null : row.tenant_id))}
            accessibleName={`${expanded === row.tenant_id ? "收起" : "管理"}租户 ${row.tenant_id} 的成员`}
          >
            {expanded === row.tenant_id ? "收起成员" : "成员管理"}
          </Button>
          <Button variant="danger" size="sm" disabled={remove.isPending} onClick={() => setPendingDelete(row)} accessibleName={`删除租户 ${row.tenant_id}`}>
            删除
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="stack" data-testid="system-tenants">
      <Callout tone="info" title="租户可见性">
        <span className="small">
          绑定租户的 token 只能看到自己的租户 (下方列表自动收窄, 不是数据丢失);
          用租户 token 创建租户会得到 403 <code className="code-inline">TENANT_FORBIDDEN</code>。
          删除租户会级联清理数据面打标行 (best-effort, 失败项见服务端日志)。
        </span>
      </Callout>

      <OrgFilterForm key={org} initial={org} onApply={setOrg} onCreate={() => setCreateOpen(true)} />

      <QueryState
        query={tenants}
        isEmpty={(rows) => rows.length === 0}
        empty={<p className="small muted">当前身份看不到任何租户 (未创建, 或你的 token 绑定了别的租户)。</p>}
      >
        {(rows) => (
          <div className="stack" data-testid="tenants-table">
            <Table ariaLabel="租户列表" columns={columns} rows={rows} rowKey={(row) => row.tenant_id} />
            {rows.map((row) =>
              expanded === row.tenant_id ? (
                <Card key={row.tenant_id} title={`成员管理: ${row.tenant_id}`} subtitle="POST/DELETE /tenants/{id}/members">
                  <MembersPanel tenant={row} />
                </Card>
              ) : null,
            )}
          </div>
        )}
      </QueryState>

      <Modal
        open={createOpen}
        title="创建租户"
        description="三个字段都可选: tenant_id 留空由后端生成; organization_id 留空归入默认组织。"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setCreateOpen(false)} disabled={create.isPending}>
              取消
            </Button>
            <Button
              variant="primary"
              data-testid="tenants-create-submit"
              loading={create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    ...(createForm.tenant_id.trim() !== "" ? { tenant_id: createForm.tenant_id.trim() } : {}),
                    ...(createForm.organization_id.trim() !== "" ? { organization_id: createForm.organization_id.trim() } : {}),
                    ...(createForm.display_name.trim() !== "" ? { display_name: createForm.display_name.trim() } : {}),
                  },
                  { onSuccess: () => setCreateOpen(false) },
                )
              }
            >
              创建
            </Button>
          </>
        }
      >
        <div className="stack">
          <TextField label="tenant_id (可选)" mono value={createForm.tenant_id} onChange={(event) => setCreateForm({ ...createForm, tenant_id: event.target.value })} />
          <TextField label="organization_id (可选)" mono value={createForm.organization_id} onChange={(event) => setCreateForm({ ...createForm, organization_id: event.target.value })} />
          <TextField label="display_name (可选)" value={createForm.display_name} onChange={(event) => setCreateForm({ ...createForm, display_name: event.target.value })} />
        </div>
      </Modal>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete ? `删除租户: ${pendingDelete.tenant_id}` : "删除租户"}
        tone="danger"
        requireText={pendingDelete?.tenant_id ?? ""}
        confirmLabel="删除租户"
        impact={
          pendingDelete ? (
            <span>
              删除租户 <code className="code-inline">{pendingDelete.tenant_id}</code> 不可恢复:
              注册表条目移除, 数据面打标行级联清理 (best-effort), 绑定该租户的 token 立即失效,
              该租户下 {pendingDelete.members.length} 个成员的隔离边界随之消失。
            </span>
          ) : (
            ""
          )
        }
        loading={remove.isPending}
        onConfirm={() => {
          if (!pendingDelete) return;
          remove.mutate(pendingDelete.tenant_id, {
            onSuccess: () => {
              setExpanded((current) => (current === pendingDelete.tenant_id ? null : current));
              setPendingDelete(null);
            },
          });
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
