import { useRef, useState } from "react";

import * as configApi from "@/api/config";
import type { ConfigApplyResult, JsonSchemaNode } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { JsonEditor } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import {
  ApplyResultPanel,
  ConflictPanel,
  ConfirmChangesDialog,
  DiffPanel,
  TransactionToolbar,
} from "@/features/config/ConfigTransactionPanels";
import { useConfigTransaction } from "@/features/config/useConfigTransaction";
import { usePatchGlobalConfig, useReloadGlobalConfig } from "@/hooks/mutations";
import { useConfigSchema, useGlobalConfig } from "@/hooks/queries";
import { useUrlString } from "@/hooks/useUrlState";
import { prettyJson } from "@/lib/format";

type Draft = Record<string, unknown>;

/** 这些节在 bootstrap 构造服务端点, 属 restart_required (契约 §4 System)。 */
const RESTART_SECTIONS = new Set(["control", "channels", "logging", "debug", "log_level"]);

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function normalizeApplyResult(result: ConfigApplyResult | { revision?: number }): ConfigApplyResult {
  return "applied" in result
    ? result
    : { applied: [], reload_required: [], restart_required: [], reloaded_agents: [], reload_errors: {}, ...result };
}

/**
 * 单个配置节的编辑事务。
 *
 * 对象节: base = 节对象, localChanges = 节内字段级变更, patch = {节名: 变更字段}
 * (后端深合并, 叶值 null = 撤销该覆盖项)。标量 / 数组节: 信封 {value: …} 承载,
 * patch = {节名: value}。校验省略 (全局配置由 PATCH 内部校验, 400 原文回显)。
 * 提交走 usePatchGlobalConfig.mutateAsync (自动失效缓存) —— 应用结果面板挂在
 * 父级 (lastResult), 编辑器按新 revision 重挂载不会把结果面板带走。
 */
function SectionEditor({
  section,
  baseValue,
  revision,
  onApplied,
}: {
  section: string;
  baseValue: unknown;
  revision: number | undefined;
  onApplied: (result: ConfigApplyResult) => void;
}) {
  const patch = usePatchGlobalConfig();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [shapeError, setShapeError] = useState<string | null>(null);

  // 缺节的对象节按空对象起步 (PATCH 会创建该节)。
  const objectMode = baseValue === undefined || isPlainObject(baseValue);
  const initial: Draft = objectMode ? { ...(isPlainObject(baseValue) ? baseValue : {}) } : { value: baseValue };
  const initialText = objectMode ? prettyJson(initial) : JSON.stringify(baseValue, null, 2);
  const [text, setText] = useState(initialText);
  const lastReload = useRef<unknown>(undefined);

  const transaction = useConfigTransaction<Draft>({
    base: initial,
    revision,
    submit: (changes, ifMatch) =>
      patch.mutateAsync({
        patch: objectMode ? { [section]: changes } : { [section]: (changes as Draft).value ?? null },
        ifMatch,
      }),
    reload: async () => {
      const fresh = await configApi.getGlobalConfig();
      const value = (fresh.config ?? {})[section];
      lastReload.current = value;
      return objectMode ? (isPlainObject(value) ? value : {}) : { value };
    },
    onApplied: (result) => onApplied(normalizeApplyResult(result)),
  });

  const syncTextFromServer = (merged?: Draft) => {
    const value = lastReload.current;
    const serverDraft: Draft = objectMode ? (isPlainObject(value) ? value : {}) : { value };
    const next = merged ?? serverDraft;
    setText(objectMode ? prettyJson(next) : JSON.stringify(next.value ?? null, null, 2));
  };

  const onPrepare = () => {
    void transaction.prepare().then((outcome) => {
      if (outcome !== "blocked") setConfirmOpen(true);
    });
  };

  return (
    <div className="stack" data-testid={`system-config-section-${section}`}>
      <TransactionToolbar
        transaction={transaction}
        revision={revision}
        onPrepare={onPrepare}
        onReset={() => {
          transaction.reset();
          setText(initialText);
          setShapeError(null);
        }}
        prepareLabel="校验并预览变更"
        extra={
          RESTART_SECTIONS.has(section) ? <Badge tone="warning">restart_required 节</Badge> : undefined
        }
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
            busy={transaction.busy}
            onAdoptServer={() => {
              void transaction.adoptServerVersion().then(() => syncTextFromServer());
            }}
            onRebase={() => {
              const replay = transaction.localChanges;
              void transaction.rebaseOnServer().then(() => {
                // 重放后的草稿 = 服务器最新值 + 我改过的字段, 文本镜像同步到该状态。
                const value = lastReload.current;
                const serverDraft: Draft = objectMode ? (isPlainObject(value) ? value : {}) : { value };
                syncTextFromServer({ ...serverDraft, ...replay });
              });
            }}
          />
        </div>
      ) : null}

      {shapeError ? (
        <Callout tone="warning" title="形状不匹配 (未写入草稿)">
          <span className="small">{shapeError}</span>
        </Callout>
      ) : null}

      {transaction.changes.length > 0 ? (
        <div data-testid="config-diff-panel">
          <DiffPanel changes={transaction.changes} title={`变更预览 (config.${section})`} />
        </div>
      ) : null}

      <JsonEditor
        label={`config.${section} (JSON)`}
        hint={
          objectMode
            ? "整个节对象; 叶值 null = 撤销该覆盖项 (回落 config.jsonc / 默认)。敏感键回传哨兵 = 未修改。"
            : "该节是标量 / 数组: 直接编辑 JSON 值 (如 \"info\"、[\"a\",\"b\"]); null = 撤销覆盖。"
        }
        rows={16}
        value={text}
        onChange={(next) => {
          setText(next);
          try {
            const parsed: unknown = JSON.parse(next);
            if (objectMode) {
              if (isPlainObject(parsed)) {
                setShapeError(null);
                transaction.setDraft(parsed);
              } else {
                setShapeError(
                  `该节是 JSON 对象, 当前输入解析为${Array.isArray(parsed) ? "数组" : ` ${typeof parsed}`}, 未写入草稿。`,
                );
              }
            } else {
              setShapeError(null);
              transaction.setDraft({ value: parsed });
            }
          } catch {
            // 语法错误由 JsonEditor 提示, 不传播半成品。
          }
        }}
      />

      <div className="row row--tight">
        <Button
          variant="primary"
          data-testid="system-config-prepare"
          onClick={onPrepare}
          disabled={!transaction.isDirty || transaction.busy}
          loading={transaction.busy}
        >
          校验并预览变更
        </Button>
        <span className="small muted">
          PATCH /config/global 深合并 + If-Match revision={revision ?? "—"}; 结果面板会严格区分 applied /
          reload_required / restart_required。
        </span>
      </div>

      <ConfirmChangesDialog
        open={confirmOpen}
        changes={transaction.changes}
        highImpact={transaction.highImpact}
        busy={transaction.busy}
        title={`提交 config.${section} 的变更`}
        onConfirm={() => {
          setConfirmOpen(false);
          void transaction.commit();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

/** 节列表: 按 schema properties 渲染标题 + description (22 顶层键)。 */
function SectionList({
  properties,
  config,
  onOpen,
}: {
  properties: Record<string, JsonSchemaNode>;
  config: Record<string, unknown>;
  onOpen: (section: string) => void;
}) {
  const names = Object.keys(properties);
  return (
    <div className="stack" data-testid="system-config-sections">
      <p className="small muted">
        共 {names.length} 个顶层配置节 (来自 GET /config/schema, pydantic 生成)。点击某节进入 JSON 编辑事务;
        当前 override revision 显示在编辑器工具条上。
      </p>
      <div className="stack stack--tight">
        {names.map((name) => {
          const node = properties[name];
          const present = name in config;
          return (
            <Card key={name} flush>
              <div className="row row--between" style={{ flexWrap: "wrap", gap: "0.5rem", padding: "0.75rem 1rem" }}>
                <div className="stack stack--tight" style={{ maxWidth: "48rem" }}>
                  <span className="row row--tight" style={{ flexWrap: "wrap" }}>
                    <code className="code-inline">{name}</code>
                    {node?.type ? <Badge>{Array.isArray(node.type) ? node.type.join(" | ") : node.type}</Badge> : null}
                    {RESTART_SECTIONS.has(name) ? <Badge tone="warning">restart_required</Badge> : null}
                    {!present ? <Badge tone="neutral">当前无覆盖 / 未出现在有效配置</Badge> : null}
                  </span>
                  {node?.description ? <span className="small muted">{node.description}</span> : null}
                </div>
                <Button variant="secondary" size="sm" onClick={() => onOpen(name)} accessibleName={`编辑配置节 ${name}`}>
                  编辑
                </Button>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 全局配置 tab (F2 配置编辑事务验收点之二)。
 *
 * useGlobalConfig 拿 {config, revision}, useConfigSchema 拿 22 顶层键 →
 * 节列表 (?section= 写 URL, Extensions 域 MCP tab 深链到 section=mcp) →
 * 节内 JSON 编辑事务。"从磁盘重读并热应用" = POST /config/global/reload。
 */
export default function GlobalConfigTab() {
  const config = useGlobalConfig();
  const schema = useConfigSchema();
  const reload = useReloadGlobalConfig();
  const [section, setSection] = useUrlString("section");
  const [lastResult, setLastResult] = useState<ConfigApplyResult | null>(null);

  return (
    <div className="stack" data-testid="system-config">
      <Callout tone="warning" title="restart_required 节">
        <span className="small">
          <code className="code-inline">control</code> / <code className="code-inline">channels</code> /{" "}
          <code className="code-inline">logging</code> / <code className="code-inline">debug</code> /{" "}
          <code className="code-inline">log_level</code> 在 bootstrap 时构造服务端点 ——
          修改后落在 restart_required 分区, <strong>需重启进程才生效</strong>;
          应用结果面板会如实区分, 不假装热更成功 (§8.2 规则 6)。
        </span>
      </Callout>

      <Callout tone="info" title="脱敏哨兵与 null 语义">
        <span className="small">
          敏感键 GET 回显为 <code className="code-inline">__ISAC_REDACTED__</code>: 编辑时原样回传哨兵 =
          未修改 (后端剥离后沿用原值), 要改值直接以新值覆盖 (仅存在于表单状态, 经 TLS 提交, 不落浏览器存储);
          叶值 <code className="code-inline">null</code> = 撤销该覆盖项, 回落到 config.jsonc / 默认值。
        </span>
      </Callout>

      {lastResult ? <ApplyResultPanel result={lastResult} onClose={() => setLastResult(null)} /> : null}

      <div className="row row--tight" style={{ flexWrap: "wrap" }}>
        <Button
          variant="secondary"
          size="sm"
          data-testid="system-config-reload"
          loading={reload.isPending}
          onClick={() => reload.mutate(undefined, { onSuccess: (result) => setLastResult(result) })}
        >
          从磁盘重读并热应用
        </Button>
        <span className="small muted">
          POST /config/global/reload: 手改 config.jsonc / override 后免重启生效 (restart_required 节仍需重启)。
        </span>
      </div>

      <QueryState query={config}>
        {(configData) => (
          <QueryState query={schema}>
            {(schemaData) => {
              const properties = schemaData.properties ?? {};
              if (section === "") {
                return (
                  <SectionList
                    properties={properties}
                    config={configData.config ?? {}}
                    onOpen={(name) => setSection(name)}
                  />
                );
              }
              const node = properties[section];
              return (
                <div className="stack">
                  <div className="row row--tight" style={{ flexWrap: "wrap" }}>
                    <Button variant="ghost" size="sm" onClick={() => setSection("")} accessibleName="返回配置节列表">
                      ← 全部配置节
                    </Button>
                    <strong className="mono">{section}</strong>
                    {node?.description ? <span className="small muted">{node.description}</span> : null}
                    {RESTART_SECTIONS.has(section) ? <Badge tone="warning">restart_required</Badge> : null}
                  </div>
                  <SectionEditor
                    key={`${section}:${configData.revision}`}
                    section={section}
                    baseValue={(configData.config ?? {})[section]}
                    revision={configData.revision}
                    onApplied={setLastResult}
                  />
                </div>
              );
            }}
          </QueryState>
        )}
      </QueryState>
    </div>
  );
}
