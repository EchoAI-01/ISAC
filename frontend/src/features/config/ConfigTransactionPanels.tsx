import type { ReactNode } from "react";

import type { ConfigApplyResult, ConfigDiffChange } from "@/api/types";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { DiffTable } from "@/components/DiffTable";
import { ConfirmDialog, Modal } from "@/components/Tabs";
import type { ConfigTransaction } from "./useConfigTransaction";

/**
 * 配置编辑事务的展示层组件 (与 useConfigTransaction 配套)。
 *
 * 之所以抽成共享组件: AgentConfig 编辑 (Agents 域) 与全局配置编辑 (System 域)
 * 走同一套事务与同一套 §8.2 规则, 两处各写一遍必然漂移。
 */

export interface TransactionToolbarProps {
  transaction: ConfigTransaction<Record<string, unknown>>;
  revision: number | undefined;
  onPrepare: () => void;
  onReset: () => void;
  prepareLabel?: string;
  extra?: ReactNode;
}

/** 事务操作条: 显示当前 revision + 校验/Diff/重置入口。 */
export function TransactionToolbar({
  transaction,
  revision,
  onPrepare,
  onReset,
  prepareLabel = "校验并预览变更",
  extra,
}: TransactionToolbarProps) {
  return (
    <div className="row row--between">
      <div className="row row--tight small">
        <span className="muted">基线 revision</span>
        <Badge tone="primary">{revision ?? "—"}</Badge>
        {transaction.isDirty ? (
          <Badge tone="warning">
            本地 {Object.keys(transaction.localChanges).length} 处未提交变更
          </Badge>
        ) : (
          <Badge>与服务端一致</Badge>
        )}
      </div>
      <div className="row row--tight">
        {extra}
        <Button variant="secondary" size="sm" onClick={onReset} disabled={!transaction.isDirty || transaction.busy}>
          放弃本地变更
        </Button>
        <Button size="sm" onClick={onPrepare} disabled={!transaction.isDirty || transaction.busy} loading={transaction.busy}>
          {prepareLabel}
        </Button>
      </div>
    </div>
  );
}

/** 校验结果面板 (后端 /config/validate 的 errors 原样呈现)。 */
export function ValidationPanel({ validation }: { validation: ConfigApplyResult | null | { valid?: boolean; errors?: string[] } }) {
  if (!validation) return null;
  const record = validation as { valid?: boolean; errors?: string[] };
  if (record.valid === undefined) return null;
  if (record.valid) {
    return (
      <Callout tone="success" title="服务端校验通过">
        字段级校验由后端 <code className="code-inline">POST /config/validate</code> 执行 (前端不复制校验规则)。
      </Callout>
    );
  }
  return (
    <Callout tone="danger" title="服务端校验未通过">
      <ul className="stack stack--tight" style={{ margin: 0, paddingLeft: "1.2rem" }}>
        {(record.errors ?? []).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </Callout>
  );
}

/** Diff 预览面板 (提交前必看; 高影响行带标记)。 */
export function DiffPanel({
  changes,
  isHighImpact,
  title = "变更预览 (POST /config/diff)",
}: {
  changes: ConfigDiffChange[];
  isHighImpact?: (change: ConfigDiffChange) => boolean;
  title?: string;
}) {
  if (changes.length === 0) return null;
  return (
    <div className="stack stack--tight">
      <div className="row row--between">
        <strong className="small">{title}</strong>
        <span className="small muted">{changes.length} 个字段</span>
      </div>
      <DiffTable changes={changes} isHighImpact={isHighImpact} />
    </div>
  );
}

export interface ConfirmChangesDialogProps {
  open: boolean;
  changes: ConfigDiffChange[];
  highImpact: ConfigDiffChange[];
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title?: string;
  isHighImpact?: (change: ConfigDiffChange) => boolean;
}

/**
 * 提交前确认 (§8.2 规则 2)。
 *
 * 有高影响变更时要求逐项可见 + 显式确认; 无高影响变更时同样列出 diff,
 * 但按钮文案降级为"提交变更"。
 */
export function ConfirmChangesDialog({
  open,
  changes,
  highImpact,
  busy,
  onConfirm,
  onCancel,
  title,
  isHighImpact,
}: ConfirmChangesDialogProps) {
  if (highImpact.length > 0) {
    return (
      <ConfirmDialog
        open={open}
        title={title ?? `确认 ${highImpact.length} 项高影响变更`}
        tone="danger"
        loading={busy}
        confirmLabel="我已理解影响, 提交"
        impact={
          <div className="stack stack--tight">
            <div>
              以下 {highImpact.length} 项属于高影响变更 (能力开关 / 凭据 / 命名空间 / 启用状态),
              提交后会热重载运行中的 Agent:
            </div>
            <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
              {highImpact.map((change) => (
                <li key={change.field}>
                  <code className="code-inline">{change.field}</code>
                </li>
              ))}
            </ul>
          </div>
        }
        onConfirm={onConfirm}
        onCancel={onCancel}
      >
        <DiffPanel changes={changes} isHighImpact={isHighImpact} title="完整变更预览" />
      </ConfirmDialog>
    );
  }

  return (
    <Modal
      open={open}
      wide
      title={title ?? "确认提交变更"}
      description="提交前请核对结构化 diff; PATCH 会带 If-Match 乐观锁, revision 不符将返回 409。"
      onClose={onCancel}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            返回编辑
          </Button>
          <Button onClick={onConfirm} loading={busy}>
            提交变更
          </Button>
        </>
      }
    >
      <DiffPanel changes={changes} isHighImpact={isHighImpact} />
    </Modal>
  );
}

/** 409 冲突面板 (§8.2 规则 3: 展示服务器版本与本地变更, 不静默覆盖)。 */
export function ConflictPanel({
  conflict,
  localChanges,
  onAdoptServer,
  onRebase,
  busy,
}: {
  conflict: NonNullable<ConfigTransaction<Record<string, unknown>>["conflict"]>;
  localChanges: Record<string, unknown>;
  onAdoptServer: () => void;
  onRebase: () => void;
  busy?: boolean;
}) {
  const localFields = Object.keys(localChanges);
  return (
    <Callout tone="danger" title="配置冲突 (409 CONFIG_CONFLICT)">
      <div className="stack stack--tight">
        <div>
          提交时基线 revision = <strong>{conflict.expectedRevision ?? "未知"}</strong>, 服务器当前 revision ={" "}
          <strong>{conflict.serverRevision ?? "未知"}</strong> —— 期间有人改过同一份配置。
        </div>
        <div>
          我的本地变更涉及 {localFields.length} 个字段:{" "}
          {localFields.map((field) => (
            <code className="code-inline" key={field} style={{ marginRight: "0.25rem" }}>
              {field}
            </code>
          ))}
        </div>
        <div className="row row--tight">
          <Button variant="secondary" size="sm" onClick={onRebase} disabled={busy}>
            以服务器版本为基线重放我的变更
          </Button>
          <Button variant="danger" size="sm" onClick={onAdoptServer} disabled={busy}>
            放弃我的变更, 载入服务器版本
          </Button>
        </div>
        <div className="small muted">
          两种方式都不会静默覆盖: 重放会把服务器最新值作为新基线, 再叠加你改过的字段, 需要重新预览并提交。
        </div>
      </div>
    </Callout>
  );
}

/**
 * 应用结果面板 (§8.2 规则 6: applied / reload_required / restart_required 严格区分)。
 *
 * restart_required 非空时必须明确告知"需要重启才生效", 不能显示成"已生效"。
 */
export function ApplyResultPanel({
  result,
  onClose,
}: {
  result: ConfigApplyResult;
  onClose?: () => void;
}) {
  const restart = result.restart_required ?? [];
  const reloadRequired = result.reload_required ?? [];
  const applied = result.applied ?? [];
  const errors = Object.entries(result.reload_errors ?? {});
  const tone = errors.length > 0 || restart.length > 0 ? "warning" : "success";

  return (
    <Callout
      tone={tone}
      title={errors.length > 0 ? "部分生效 (有 Agent 重建失败)" : restart.length > 0 ? "部分变更需重启后生效" : "变更已热生效"}
    >
      <div className="stack stack--tight">
        <dl className="kv">
          <div style={{ display: "contents" }}>
            <dt>applied (已热生效)</dt>
            <dd>{applied.length > 0 ? applied.map((item) => <code className="code-inline" key={item}>{item}</code>) : "—"}</dd>
          </div>
          <div style={{ display: "contents" }}>
            <dt>reload_required</dt>
            <dd>{reloadRequired.length > 0 ? reloadRequired.join(", ") : "空 (Agent 重建已在请求内完成)"}</dd>
          </div>
          <div style={{ display: "contents" }}>
            <dt>restart_required</dt>
            <dd>
              {restart.length > 0 ? (
                <>
                  {restart.map((item) => (
                    <code className="code-inline" key={item} style={{ marginRight: "0.25rem" }}>
                      {item}
                    </code>
                  ))}
                  <span className="small muted"> — 这些节在 bootstrap 构造服务端点, 需重启进程才生效。</span>
                </>
              ) : (
                "无"
              )}
            </dd>
          </div>
          <div style={{ display: "contents" }}>
            <dt>reloaded_agents</dt>
            <dd>{(result.reloaded_agents ?? []).join(", ") || "无运行中 Agent 需要重建"}</dd>
          </div>
          {typeof result.revision === "number" ? (
            <div style={{ display: "contents" }}>
              <dt>新 revision</dt>
              <dd>
                <Badge tone="primary">{result.revision}</Badge>
              </dd>
            </div>
          ) : null}
        </dl>
        {errors.length > 0 ? (
          <div className="small">
            <strong>重建失败 (旧实例已保留):</strong>
            <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.2rem" }}>
              {errors.map(([agentId, message]) => (
                <li key={agentId}>
                  <code className="code-inline">{agentId}</code>: {message} (明细见服务端日志)
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {onClose ? (
          <div className="row row--end">
            <Button variant="ghost" size="sm" onClick={onClose}>
              知道了
            </Button>
          </div>
        ) : null}
      </div>
    </Callout>
  );
}
