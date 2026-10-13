import { useState } from "react";

import type { IdentityConflict } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { CodeBlock, ShortId } from "@/components/DataDisplay";
import { TextField } from "@/components/Form";
import { QueryState } from "@/components/QueryState";
import { Modal } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useBindIdentity, useResolveConflict } from "@/hooks/mutations";
import { useIdentityConflicts } from "@/hooks/queries";
import { formatTimestamp, prettyJson } from "@/lib/format";

/** candidates 是后端直出的 JSON 字符串: 能解析就美化展示, 解析失败原样显示。 */
function CandidatesCell({ raw }: { raw: string }) {
  const [open, setOpen] = useState(false);
  let pretty: string | null;
  try {
    pretty = prettyJson(JSON.parse(raw));
  } catch {
    pretty = null;
  }
  return (
    <div className="stack stack--tight">
      <Button variant="ghost" size="sm" onClick={() => setOpen((current) => !current)} accessibleName={`${open ? "收起" : "展开"}候选人详情`}>
        {open ? "收起" : "展开"}
      </Button>
      {open ? (
        pretty !== null ? (
          <CodeBlock ariaLabel="冲突候选人 (解析后)" maxHeight="14rem">
            {pretty}
          </CodeBlock>
        ) : (
          <Callout tone="warning" title="candidates 不是合法 JSON, 原样显示">
            <code className="code-inline small">{raw}</code>
          </Callout>
        )
      ) : null}
    </div>
  );
}

/** 未裁决冲突列表 + 裁决 (指定 person_id)。 */
function ConflictsPanel() {
  const conflicts = useIdentityConflicts();
  const resolve = useResolveConflict();
  const [target, setTarget] = useState<IdentityConflict | null>(null);
  const [personId, setPersonId] = useState("");

  const columns: Array<Column<IdentityConflict>> = [
    { key: "conflict_id", header: "conflict_id", label: "conflict_id", render: (row) => <ShortId value={row.conflict_id} /> },
    { key: "person_id", header: "当前 person_id", label: "当前 person_id", render: (row) => <span className="mono small">{row.person_id || "—"}</span> },
    {
      key: "confidence",
      header: "最高置信度",
      label: "最高置信度",
      align: "right",
      render: (row) => (
        <Badge tone={row.highest_confidence >= 0.75 ? "warning" : "neutral"} title="低于裁决阈值才会进入冲突队列">
          {row.highest_confidence}
        </Badge>
      ),
    },
    { key: "created", header: "产生时间", label: "产生时间", render: (row) => <span className="nowrap">{formatTimestamp(row.created_at)}</span> },
    {
      key: "resolved",
      header: "状态",
      label: "状态",
      render: (row) => (
        <Badge tone={row.resolved ? "success" : "warning"} dot>
          {row.resolved ? "已裁决" : "待裁决"}
        </Badge>
      ),
    },
    { key: "candidates", header: "候选人", label: "候选人", render: (row) => <CandidatesCell raw={row.candidates} /> },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button
          variant="primary"
          size="sm"
          disabled={resolve.isPending || row.resolved === 1}
          onClick={() => {
            setTarget(row);
            setPersonId(row.person_id);
          }}
          accessibleName={`裁决冲突 ${row.conflict_id}`}
        >
          裁决
        </Button>
      ),
    },
  ];

  return (
    <Card title="未裁决的低置信度冲突" subtitle="GET /api/v1/identity/conflicts · 返回数组; 裁决 = 人工指定最终 person_id">
      <QueryState
        query={conflicts}
        isEmpty={(rows) => rows.length === 0}
        empty={<p className="small muted">当前没有待裁决的身份冲突 (归一层置信度都足够, 或尚无跨平台身份数据)。</p>}
      >
        {(rows) => (
          <div data-testid="identity-conflicts-table">
            <Table ariaLabel="身份冲突列表" columns={columns} rows={rows} rowKey={(row) => row.conflict_id} />
          </div>
        )}
      </QueryState>

      <Modal
        open={target !== null}
        title="裁决身份冲突"
        description="指定该身份簇的最终 person_id: 裁决后归一层将候选人合并到该 person 下, 记忆画像随之归并。"
        onClose={() => setTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setTarget(null)} disabled={resolve.isPending}>
              取消
            </Button>
            <Button
              variant="primary"
              data-testid="identity-resolve-submit"
              disabled={target === null || personId.trim() === "" || resolve.isPending}
              loading={resolve.isPending}
              onClick={() => {
                if (!target) return;
                resolve.mutate(
                  { conflictId: target.conflict_id, personId: personId.trim() },
                  { onSuccess: () => setTarget(null) },
                );
              }}
            >
              确认裁决
            </Button>
          </>
        }
      >
        <div className="stack">
          {target ? (
            <p className="small muted">
              冲突 <code className="code-inline">{target.conflict_id}</code> · 当前 person_id{" "}
              <code className="code-inline">{target.person_id || "(空)"}</code> · 最高置信度 {target.highest_confidence}
            </p>
          ) : null}
          <TextField
            label="person_id"
            required
            mono
            hint="最终归属的人物 ID (可沿用当前值, 或填候选人中的另一个)"
            value={personId}
            onChange={(event) => setPersonId(event.target.value)}
          />
        </div>
      </Modal>
    </Card>
  );
}

/** 手动绑定表单: 把某平台账号直接绑到指定 person_id。 */
function BindPanel() {
  const bind = useBindIdentity();
  const [form, setForm] = useState({ person_id: "", platform: "", platform_user_id: "", display_name: "", connection_id: "" });

  const ok = form.person_id.trim() !== "" && form.platform.trim() !== "" && form.platform_user_id.trim() !== "";

  return (
    <Card title="手动绑定身份" subtitle="POST /api/v1/identity/bind · 跳过归一推断, 把平台账号直接挂到指定 person">
      <div className="stack">
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="grow" style={{ minWidth: "14rem" }}>
            <TextField
              label="person_id"
              required
              mono
              value={form.person_id}
              onChange={(event) => setForm({ ...form, person_id: event.target.value })}
            />
          </div>
          <div className="grow" style={{ minWidth: "10rem" }}>
            <TextField
              label="platform"
              required
              mono
              hint="如 feishu / telegram"
              value={form.platform}
              onChange={(event) => setForm({ ...form, platform: event.target.value })}
            />
          </div>
          <div className="grow" style={{ minWidth: "12rem" }}>
            <TextField
              label="platform_user_id"
              required
              mono
              value={form.platform_user_id}
              onChange={(event) => setForm({ ...form, platform_user_id: event.target.value })}
            />
          </div>
        </div>
        <div className="row" style={{ flexWrap: "wrap" }}>
          <div className="grow" style={{ minWidth: "12rem" }}>
            <TextField
              label="display_name (可选)"
              value={form.display_name}
              onChange={(event) => setForm({ ...form, display_name: event.target.value })}
            />
          </div>
          <div className="grow" style={{ minWidth: "12rem" }}>
            <TextField
              label="connection_id (可选)"
              mono
              hint="同平台多连接 (多 bot) 时指明归属"
              value={form.connection_id}
              onChange={(event) => setForm({ ...form, connection_id: event.target.value })}
            />
          </div>
        </div>
        <div className="row row--tight">
          <Button
            variant="primary"
            data-testid="identity-bind-submit"
            disabled={!ok || bind.isPending}
            loading={bind.isPending}
            onClick={() =>
              bind.mutate({
                person_id: form.person_id.trim(),
                platform: form.platform.trim(),
                platform_user_id: form.platform_user_id.trim(),
                ...(form.display_name.trim() !== "" ? { display_name: form.display_name.trim() } : {}),
                ...(form.connection_id.trim() !== "" ? { connection_id: form.connection_id.trim() } : {}),
              })
            }
          >
            绑定
          </Button>
          {!ok ? <span className="small muted">person_id / platform / platform_user_id 必填。</span> : null}
        </div>
      </div>
    </Card>
  );
}

/**
 * 身份归一 tab (S4): 冲突裁决 + 手动绑定。
 * candidates 是 JSON 字符串 (后端直出), 解析失败原样显示, 不静默丢弃。
 */
export default function IdentityTab() {
  return (
    <div className="stack" data-testid="system-identity">
      <Callout tone="info" title="身份归一层做什么">
        <span className="small">
          同一自然人在不同平台 / 不同账号的 ID 会被归一到同一个 person_id (置信度足够时自动合并);
          低置信度的进入下方冲突队列等人工裁决。裁决与绑定都会影响记忆画像的归属, 操作写入审计。
        </span>
      </Callout>
      <ConflictsPanel />
      <BindPanel />
    </div>
  );
}
