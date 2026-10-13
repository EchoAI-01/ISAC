import { useState } from "react";

import type { ChannelBinding, RoutingRules } from "@/api/types";
import { Button } from "@/components/Button";
import { Card, Callout } from "@/components/Card";
import { CodeBlock } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog, Modal } from "@/components/Tabs";
import { Table, type Column } from "@/components/Table";
import { useRoutingRules } from "@/hooks/queries";
import { usePutRoutingRules } from "@/hooks/mutations";
import { prettyJson } from "@/lib/format";

import {
  BindingModalBody,
  DefaultModalBody,
  type BindingDraft,
  type DefaultDraft,
} from "./RoutingRuleModals";

interface Draft {
  bindings: BindingDraft[];
  defaults: DefaultDraft[];
}

function toDraft(rules: RoutingRules): Draft {
  return {
    bindings: rules.bindings.map((b) => ({
      platform: b.platform,
      agent_id: b.agent_id,
      group_id: b.group_id ?? "",
      user_id: b.user_id ?? "",
    })),
    defaults: Object.entries(rules.default_agents).map(([platform, agent_id]) => ({ platform, agent_id })),
  };
}

function toPayload(draft: Draft): RoutingRules {
  const bindings: ChannelBinding[] = draft.bindings.map((b) => ({
    platform: b.platform.trim(),
    agent_id: b.agent_id.trim(),
    group_id: b.group_id.trim() === "" ? null : b.group_id.trim(),
    user_id: b.user_id.trim() === "" ? null : b.user_id.trim(),
  }));
  return {
    bindings,
    default_agents: Object.fromEntries(
      draft.defaults.map((d) => [d.platform.trim(), d.agent_id.trim()]),
    ),
  };
}

type Editor =
  | { kind: "binding-add" }
  | { kind: "binding-edit"; index: number }
  | { kind: "default-add" }
  | { kind: "default-edit"; index: number }
  | null;

/** 编辑器: 从服务端 GET /routing/rules 的结果深拷贝一份草稿, 本地增删改, 最后整体覆盖 PUT。 */
function RoutingRulesEditor({ initial }: { initial: RoutingRules }) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(initial));
  const [editor, setEditor] = useState<Editor>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const put = usePutRoutingRules();

  const payload = toPayload(draft);
  // initial 是服务端形状 (RoutingRules), 先归一成草稿再转回 payload 才能与本地草稿同构比较。
  const dirty = JSON.stringify(payload) !== JSON.stringify(toPayload(toDraft(initial)));
  const invalid =
    draft.bindings.some((b) => b.platform.trim() === "" || b.agent_id.trim() === "") ||
    draft.defaults.some((d) => d.platform.trim() === "" || d.agent_id.trim() === "");

  const saveBinding = (row: BindingDraft) => {
    setDraft((d) =>
      editor?.kind === "binding-edit"
        ? { ...d, bindings: d.bindings.map((b, i) => (i === editor.index ? row : b)) }
        : { ...d, bindings: [...d.bindings, row] },
    );
    setEditor(null);
  };

  const saveDefault = (row: DefaultDraft) => {
    setDraft((d) => {
      const editedIndex = editor?.kind === "default-edit" ? editor.index : -1;
      // 平台键唯一: 删除被编辑的旧行与其他同 platform 的行, 再追加新行 (重复时后写覆盖)。
      const kept = d.defaults.filter(
        (x, i) => i !== editedIndex && x.platform.trim() !== row.platform.trim(),
      );
      return { ...d, defaults: [...kept, row] };
    });
    setEditor(null);
  };

  const bindingColumns: Array<Column<BindingDraft>> = [
    { key: "platform", header: "platform", label: "platform", render: (row) => <code className="code-inline">{row.platform || "—"}</code> },
    { key: "agent_id", header: "agent_id", label: "agent_id", render: (row) => <span className="mono">{row.agent_id || "—"}</span> },
    { key: "group_id", header: "group_id", label: "group_id", render: (row) => <span className="mono">{row.group_id || "—"}</span> },
    { key: "user_id", header: "user_id", label: "user_id", render: (row) => <span className="mono">{row.user_id || "—"}</span> },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (_row, i) => (
        <div className="row row--tight">
          <Button
            variant="ghost"
            size="sm"
            accessibleName={`编辑第 ${i + 1} 条绑定`}
            onClick={() => setEditor({ kind: "binding-edit", index: i })}
          >
            编辑
          </Button>
          <Button
            variant="ghost"
            size="sm"
            accessibleName={`删除第 ${i + 1} 条绑定`}
            onClick={() => setDraft((d) => ({ ...d, bindings: d.bindings.filter((_, j) => j !== i) }))}
          >
            删除
          </Button>
        </div>
      ),
    },
  ];

  const defaultColumns: Array<Column<DefaultDraft>> = [
    { key: "platform", header: "platform", label: "platform", render: (row) => <code className="code-inline">{row.platform || "—"}</code> },
    { key: "agent_id", header: "agent_id", label: "agent_id", render: (row) => <span className="mono">{row.agent_id || "—"}</span> },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (_row, i) => (
        <div className="row row--tight">
          <Button
            variant="ghost"
            size="sm"
            accessibleName={`编辑第 ${i + 1} 条平台默认`}
            onClick={() => setEditor({ kind: "default-edit", index: i })}
          >
            编辑
          </Button>
          <Button
            variant="ghost"
            size="sm"
            accessibleName={`删除第 ${i + 1} 条平台默认`}
            onClick={() => setDraft((d) => ({ ...d, defaults: d.defaults.filter((_, j) => j !== i) }))}
          >
            删除
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="stack">
      <Callout tone="info" title="空集合的语义">
        <div className="stack">
          <p>
            <strong>空 bindings</strong>: 没有任何按平台 / 群组 / 用户的定向绑定, 入站消息完全依赖
            default_agents 的平台默认路由。
          </p>
          <p>
            <strong>空 default_agents</strong>: 任何平台都没有兜底 Agent。两者同时为空时,
            入站消息将没有可路由的 Agent —— 保存前请确认这符合预期。
          </p>
        </div>
      </Callout>

      <Card
        title="绑定规则 (bindings)"
        subtitle={`${draft.bindings.length} 条 · 本地草稿, 保存后才写入后端`}
        actions={
          <Button variant="secondary" size="sm" onClick={() => setEditor({ kind: "binding-add" })}>
            添加绑定
          </Button>
        }
      >
        <div data-testid="routing-rules-table">
          <Table
            ariaLabel="路由绑定规则 (bindings) 草稿"
            columns={bindingColumns}
            rows={draft.bindings}
            rowKey={(row, i) => `${row.platform}|${row.agent_id}|${row.group_id}|${row.user_id}|${i}`}
            empty={<p className="small muted">暂无绑定规则。保存空 bindings 表示仅靠平台默认 Agent 路由。</p>}
          />
        </div>
      </Card>

      <Card
        title="平台默认 Agent (default_agents)"
        subtitle={`${draft.defaults.length} 个平台 · 本地草稿, 保存后才写入后端`}
        actions={
          <Button variant="secondary" size="sm" onClick={() => setEditor({ kind: "default-add" })}>
            添加默认
          </Button>
        }
      >
        <Table
          ariaLabel="平台默认 Agent (default_agents) 草稿"
          columns={defaultColumns}
          rows={draft.defaults}
          rowKey={(row, i) => `${row.platform}|${i}`}
          empty={<p className="small muted">暂无平台默认 Agent。保存空 default_agents 表示无兜底路由。</p>}
        />
      </Card>

      <div className="row row--tight">
        <Button
          variant="primary"
          data-testid="routing-rules-save"
          disabled={!dirty || invalid || put.isPending}
          loading={put.isPending}
          onClick={() => setConfirmOpen(true)}
        >
          保存路由规则 (整体覆盖)
        </Button>
        <Button variant="ghost" disabled={!dirty} onClick={() => setDraft(toDraft(initial))}>
          放弃本地修改
        </Button>
        <span className="small muted">
          {!dirty ? "与服务器当前规则一致, 无需保存。" : invalid ? "存在缺 platform / agent_id 的条目, 补全后才能保存。" : "有未保存的修改。保存是覆盖式 PUT, 提交前会预览将覆盖成什么。"}
        </span>
      </div>

      <Modal
        open={editor !== null}
        title={
          editor === null
            ? ""
            : editor.kind.startsWith("binding")
              ? editor.kind === "binding-add"
                ? "添加绑定规则"
                : "编辑绑定规则"
              : editor.kind === "default-add"
                ? "添加平台默认 Agent"
                : "编辑平台默认 Agent"
        }
        onClose={() => setEditor(null)}
      >
        {editor?.kind === "binding-add" || editor?.kind === "binding-edit" ? (
          <BindingModalBody
            key={editor.kind}
            initial={
              editor.kind === "binding-edit"
                ? draft.bindings[editor.index]
                : { platform: "", agent_id: "", group_id: "", user_id: "" }
            }
            onSave={saveBinding}
            onClose={() => setEditor(null)}
          />
        ) : editor?.kind === "default-add" || editor?.kind === "default-edit" ? (
          <DefaultModalBody
            key={editor.kind}
            initial={
              editor.kind === "default-edit"
                ? draft.defaults[editor.index]
                : { platform: "", agent_id: "" }
            }
            onSave={saveDefault}
            onClose={() => setEditor(null)}
          />
        ) : null}
      </Modal>

      <ConfirmDialog
        open={confirmOpen}
        title="保存路由规则 (整体覆盖)"
        tone="danger"
        impact="PUT /api/v1/routing/rules 为覆盖式写入: 后端将用下方内容整体替换当前路由规则, 未包含在本次提交中的绑定与默认 Agent 会被删除, 并持久化到 data/routing.jsonc。"
        confirmLabel="确认覆盖保存"
        loading={put.isPending}
        onConfirm={() =>
          put.mutate(payload, { onSuccess: () => setConfirmOpen(false) })
        }
        onCancel={() => setConfirmOpen(false)}
      >
        <div className="stack">
          <p className="small muted">
            将覆盖为: {payload.bindings.length} 条绑定 ·{" "}
            {Object.keys(payload.default_agents).length} 个平台默认 Agent
          </p>
          <CodeBlock ariaLabel="待保存路由规则预览" maxHeight="20rem">
            {prettyJson(payload)}
          </CodeBlock>
        </div>
      </ConfirmDialog>
    </div>
  );
}

/**
 * 路由规则 tab: GET /routing/rules → 本地草稿编辑 → 覆盖式 PUT (提交前 ConfirmDialog 预览)。
 * mutation 自带 Toast 与缓存失效, 保存成功后 QueryState 会拿到最新规则。
 */
export default function RoutingRulesPanel() {
  const rules = useRoutingRules();
  return (
    <QueryState query={rules}>
      {(data) => <RoutingRulesEditor key={JSON.stringify(data)} initial={data} />}
    </QueryState>
  );
}
