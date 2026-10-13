import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import * as agentsApi from "@/api/agents";
import { validateConfig } from "@/api/config";
import type { AgentConfig } from "@/api/types";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { KeyValue } from "@/components/DataDisplay";
import { CheckboxField, SelectField, TextField } from "@/components/Form";
import { JsonEditor, TagInput } from "@/components/Inputs";
import {
  ApplyResultPanel,
  ConflictPanel,
  ConfirmChangesDialog,
  DiffPanel,
  TransactionToolbar,
  ValidationPanel,
} from "@/features/config/ConfigTransactionPanels";
import { useConfigTransaction } from "@/features/config/useConfigTransaction";
import { queryKeys } from "@/hooks/queryKeys";
import { prettyJson } from "@/lib/format";

import LlmConfigEditor from "./LlmConfigEditor";
import ToolsPolicyEditor from "./ToolsPolicyEditor";

type Draft = Record<string, unknown>;

const asString = (value: unknown): string => (typeof value === "string" ? value : "");
const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
const asStringRecord = (value: unknown): Record<string, string> => {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return {};
  const result: Record<string, string> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (typeof item === "string") result[key] = item;
  }
  return result;
};
const asRecord = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const asRecordOrNull = (value: unknown): Record<string, unknown> | null =>
  value === null || value === undefined ? null : asRecord(value);

/**
 * JSON 节编辑器 (persona / gating / conversation)。
 *
 * 本地文本态承载输入, 仅在能解析成对象时向草稿传播 —— 半成品 JSON 不进事务。
 * 外部基线变化 (冲突重放 / 放弃变更) 由父级 key 重挂载刷新文本。
 */
function JsonSectionField({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint?: string;
  value: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}) {
  const [text, setText] = useState(() => prettyJson(value));
  return (
    <JsonEditor
      label={label}
      hint={hint}
      rows={8}
      value={text}
      onChange={(next) => {
        setText(next);
        try {
          const parsed: unknown = JSON.parse(next);
          if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
            onChange(parsed as Record<string, unknown>);
          }
        } catch {
          // 语法错误由 JsonEditor 自身提示。
        }
      }}
    />
  );
}

const MESH_ROLES = [
  { value: "primary", label: "primary (主导: handoff 后接管对话)" },
  { value: "observer", label: "observer (只读: 收 notify / 查记忆, 不接管)" },
  { value: "candidate", label: "candidate (候选专家: 被 ask 咨询后交还)" },
];

/**
 * AgentConfig 编辑事务 (CONTROL_PLANE_SPEC §8.2, F2 验收核心)。
 *
 * 覆盖 AgentConfig 全部字段; 校验与 diff 一律走后端 (/config/validate、
 * /config/diff), 前端不复制校验规则。提交带 If-Match 乐观锁, 409 走冲突面板。
 * 提交成功后展示结果面板, 关闭时才失效缓存 → 父级按新 revision 重挂载本组件。
 */
export default function AgentConfigEditor({ agentId, initial }: { agentId: string; initial: AgentConfig }) {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [syncEpoch, setSyncEpoch] = useState(0);

  const transaction = useConfigTransaction<Draft>({
    base: { ...initial } as Draft,
    revision: initial.revision,
    validate: (candidate) => validateConfig(candidate as Partial<AgentConfig>),
    submit: (patch, ifMatch) => agentsApi.patchAgent(agentId, patch as Partial<AgentConfig>, ifMatch),
    reload: async () => ({ ...(await agentsApi.getAgentConfig(agentId)) }) as Draft,
  });

  const draft = transaction.draft;

  const onPrepare = () => {
    void transaction.prepare().then((outcome) => {
      if (outcome !== "blocked") setConfirmOpen(true);
    });
  };

  const closeResult = () => {
    transaction.closeResult();
    void queryClient.invalidateQueries({ queryKey: queryKeys.agents.all });
  };

  const onAdoptServer = () => {
    void transaction.adoptServerVersion().then(() => setSyncEpoch((epoch) => epoch + 1));
  };

  const onRebase = () => {
    void transaction.rebaseOnServer().then(() => setSyncEpoch((epoch) => epoch + 1));
  };

  const onReset = () => {
    transaction.reset();
    setSyncEpoch((epoch) => epoch + 1);
  };

  return (
    <div className="stack" data-testid="agent-config-editor">
      <KeyValue
        items={[
          { term: "agent_id", value: <code className="code-inline">{asString(draft.agent_id) || agentId}</code> },
          {
            term: "enabled",
            value: draft.enabled === true ? "是 (处理消息)" : "否 (停用中)",
          },
        ]}
      />

      <TransactionToolbar
        transaction={transaction}
        revision={initial.revision}
        onPrepare={onPrepare}
        onReset={onReset}
        prepareLabel="校验并预览变更"
      />

      {transaction.error ? (
        <Callout tone="danger" title="事务未通过 (后端原文)">
          <span className="small">{transaction.error}</span>
        </Callout>
      ) : null}

      {transaction.conflict ? (
        <div data-testid="config-conflict-panel">
          <ConflictPanel
            conflict={transaction.conflict}
            localChanges={transaction.localChanges}
            onAdoptServer={onAdoptServer}
            onRebase={onRebase}
            busy={transaction.busy}
          />
        </div>
      ) : null}

      {transaction.applyResult ? <ApplyResultPanel result={transaction.applyResult} onClose={closeResult} /> : null}

      <ValidationPanel validation={transaction.validation} />

      {transaction.changes.length > 0 ? (
        <div data-testid="config-diff-panel">
          <DiffPanel changes={transaction.changes} />
        </div>
      ) : null}

      {/* key=syncEpoch: 冲突重放 / 放弃变更后重挂载, 刷新所有本地文本镜像 */}
      <div className="stack stack--loose" key={syncEpoch}>
        <Card title="身份" subtitle="display_name / enabled / memory_namespace / mesh_role / trigger_words">
          <div className="stack">
            <TextField
              label="display_name"
              hint="展示名; 留空时各端回落为 agent_id"
              value={asString(draft.display_name)}
              onChange={(event) => transaction.patchField("display_name", event.target.value)}
            />
            <CheckboxField
              label="enabled"
              hint="停用后该 Agent 不再处理消息 (高影响变更, 提交前需二次确认)"
              checked={draft.enabled === true}
              onChange={(event) => transaction.patchField("enabled", event.target.checked)}
            />
            <TextField
              label="memory_namespace"
              mono
              hint="默认 = agent_id (私有命名空间); shared = 跨 Agent 共享。改成 shared 后, 销毁时 keep_memory=false 会被后端拒绝清理"
              value={asString(draft.memory_namespace)}
              onChange={(event) => transaction.patchField("memory_namespace", event.target.value)}
            />
            <SelectField
              label="mesh_role"
              hint="Agent 网格角色 (handoff 语义见 Channels & Routing → 互联 Link)"
              options={MESH_ROLES}
              value={asString(draft.mesh_role)}
              onChange={(event) => transaction.patchField("mesh_role", event.target.value)}
            />
            <div>
              <span className="field__label">trigger_words</span>
              <TagInput
                values={asStringArray(draft.trigger_words)}
                onChange={(next) => transaction.patchField("trigger_words", next)}
                ariaLabel="触发词"
                allowWildcard={false}
                placeholder="群聊触发词, 回车添加"
              />
            </div>
          </div>
        </Card>

        <Card title="能力" subtitle="插件 / 工具策略 / 命令 / MCP / 模型能力 —— 全部是高影响字段, 提交前逐项确认">
          <div className="stack">
            <div>
              <span className="field__label">plugins_allow</span>
              <TagInput
                values={asStringArray(draft.plugins_allow)}
                onChange={(next) => transaction.patchField("plugins_allow", next)}
                ariaLabel="插件白名单"
                placeholder="允许加载的插件名, * = 通配"
              />
            </div>
            <div>
              <span className="field__label">plugins_deny</span>
              <TagInput
                values={asStringArray(draft.plugins_deny)}
                onChange={(next) => transaction.patchField("plugins_deny", next)}
                ariaLabel="插件黑名单"
                placeholder="禁止加载的插件名, * = 通配"
              />
            </div>
            <div className="stack stack--tight">
              <span className="field__label">tools_policy (四档: allow / restricted / ask / deny)</span>
              <ToolsPolicyEditor
                value={asStringRecord(draft.tools_policy)}
                onChange={(next) => transaction.patchField("tools_policy", next)}
              />
            </div>
            <div>
              <span className="field__label">commands_allow</span>
              <TagInput
                values={asStringArray(draft.commands_allow)}
                onChange={(next) => transaction.patchField("commands_allow", next)}
                ariaLabel="命令白名单"
                placeholder="允许的命令名, * = 通配"
              />
            </div>
            <div>
              <span className="field__label">mcp_servers</span>
              <TagInput
                values={asStringArray(draft.mcp_servers)}
                onChange={(next) => transaction.patchField("mcp_servers", next)}
                ariaLabel="MCP 服务器列表"
                allowWildcard={false}
                placeholder="允许该 Agent 连接的 MCP server 名 (须已在全局配置 mcp.servers 中定义)"
              />
            </div>
            <div>
              <span className="field__label">model_capabilities_allow</span>
              <TagInput
                values={asStringArray(draft.model_capabilities_allow)}
                onChange={(next) => transaction.patchField("model_capabilities_allow", next)}
                ariaLabel="模型能力白名单"
                allowWildcard={false}
                placeholder="允许的模型能力 (如 vision / audio), 回车添加"
              />
            </div>
          </div>
        </Card>

        <Card title="LLM 覆写" subtitle="null = 继承全局 llm 节; api_key 走脱敏哨兵 (只写不回显)">
          <LlmConfigEditor
            value={asRecordOrNull(draft.llm)}
            onChange={(next) => transaction.patchField("llm", next)}
          />
        </Card>

        <Card title="行为节 (JSON)" subtitle="persona / gating / conversation —— 语法校验在前端, 字段校验走后端 /config/validate">
          <div className="stack">
            <JsonSectionField
              label="persona"
              hint="人格设定 (名字 / 性格 / 说话风格等), 对象结构由后端 persona 模型校验"
              value={asRecord(draft.persona)}
              onChange={(next) => transaction.patchField("persona", next)}
            />
            <JsonSectionField
              label="gating"
              hint="发言门控参数 (何时插话 / 冷却等), 对象结构由后端校验"
              value={asRecord(draft.gating)}
              onChange={(next) => transaction.patchField("gating", next)}
            />
            <JsonSectionField
              label="conversation"
              hint="会话参数 (上下文长度 / 分隔符等), 对象结构由后端校验"
              value={asRecord(draft.conversation)}
              onChange={(next) => transaction.patchField("conversation", next)}
            />
          </div>
        </Card>
      </div>

      <div className="row row--tight">
        <Button
          variant="primary"
          data-testid="agent-config-prepare"
          onClick={onPrepare}
          disabled={!transaction.isDirty || transaction.busy}
          loading={transaction.busy}
        >
          校验并预览变更
        </Button>
        <span className="small muted">
          事务顺序: 校验 (/config/validate) → Diff (/config/diff) → 确认 → PATCH (If-Match revision={initial.revision})。
          非法 tools_policy 档位等错误会被后端 400 拒绝并原样显示。
        </span>
      </div>

      <ConfirmChangesDialog
        open={confirmOpen}
        changes={transaction.changes}
        highImpact={transaction.highImpact}
        busy={transaction.busy}
        title={`提交 Agent ${agentId} 的配置变更`}
        onConfirm={() => {
          setConfirmOpen(false);
          void transaction.commit();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
