import { useCallback, useMemo, useState } from "react";

import * as configApi from "@/api/config";
import { isApiError } from "@/api/errors";
import type { ConfigApplyResult, ConfigDiffChange, ConfigDiffResult, ConfigValidateResult } from "@/api/types";

/**
 * 配置编辑事务 (CONTROL_PLANE_SPEC §8.2, F2 验收核心)。
 *
 * 状态机:
 * ```text
 * idle → editing(改表单) → validating(POST /config/validate)
 *      → diffing(POST /config/diff) → confirming(高影响变更二次确认)
 *      → committing(PATCH + If-Match) → applied | conflict(409)
 * ```
 *
 * 三条硬规则:
 * 1. **前端不复制校验规则** (§8.2 规则 1): 字段校验一律走后端 `/config/validate`,
 *    前端只做 JSON 语法与"必填非空"这类纯语法检查;
 * 2. **不静默覆盖** (规则 3): 409 时展示服务器 revision 与本地变更, 让用户显式选择
 *    "载入服务器版本" 或 "以服务器版本为基线重放我的变更";
 * 3. **不假装热更成功** (规则 6): applied / reload_required / restart_required 分区展示。
 */

export type TransactionPhase =
  | "idle"
  | "editing"
  | "validating"
  | "invalid"
  | "diffing"
  | "confirming"
  | "committing"
  | "applied"
  | "conflict"
  | "failed";

export interface ConfigTransactionOptions<T extends Record<string, unknown>> {
  /** 服务端载入的基线配置 (含 revision)。 */
  base: T;
  /** 基线 revision (乐观锁 If-Match); 全局配置来自 override revision。 */
  revision: number | undefined;
  /** 字段校验 (AgentConfig 走 /config/validate; 全局配置走 PATCH 内部校验, 可省)。 */
  validate?: (candidate: T) => Promise<ConfigValidateResult>;
  /** 提交 (AgentConfig → PATCH /agents/{id}; 全局 → PATCH /config/global)。 */
  submit: (patch: Record<string, unknown>, ifMatch: number | undefined) => Promise<ConfigApplyResult | { revision?: number }>;
  /** 冲突后重新载入基线。 */
  reload: () => Promise<T>;
  /** 高影响判定 (默认用 config.isHighImpactChange)。 */
  isHighImpact?: (change: ConfigDiffChange) => boolean;
  /** 提交成功回调 (页面用于失效缓存/提示)。 */
  onApplied?: (result: ConfigApplyResult | { revision?: number }) => void;
}

export interface ConfigTransaction<T extends Record<string, unknown>> {
  phase: TransactionPhase;
  draft: T;
  setDraft: (next: T) => void;
  patchField: <K extends keyof T>(key: K, value: T[K]) => void;
  isDirty: boolean;
  /** 本地字段级变更 (base → draft), 用于冲突时"重放我的变更"。 */
  localChanges: Record<string, unknown>;
  validation: ConfigValidateResult | null;
  changes: ConfigDiffChange[];
  highImpact: ConfigDiffChange[];
  applyResult: ConfigApplyResult | null;
  error: string | null;
  /** 409 冲突信息 (服务器当前 revision)。 */
  conflict: { expectedRevision: number | undefined; serverRevision: number | undefined } | null;
  busy: boolean;
  runValidate: () => Promise<boolean>;
  runDiff: () => Promise<ConfigDiffChange[]>;
  /** 校验 → diff → (必要时) 进确认态; 返回是否可直接提交 (无高影响变更)。 */
  prepare: () => Promise<"ready" | "confirm" | "blocked">;
  commit: () => Promise<boolean>;
  /** 冲突解决: 放弃本地变更, 载入服务器版本。 */
  adoptServerVersion: () => Promise<void>;
  /** 冲突解决: 以服务器版本为基线重放本地变更 (不静默覆盖)。 */
  rebaseOnServer: () => Promise<void>;
  reset: () => void;
  closeResult: () => void;
}

/** 计算 base → draft 的字段级变更 (只取顶层键, 与后端 _compute_diff 同口径)。 */
export function computeLocalChanges<T extends Record<string, unknown>>(base: T, draft: T): Record<string, unknown> {
  const changes: Record<string, unknown> = {};
  const keys = new Set([...Object.keys(base), ...Object.keys(draft)]);
  for (const key of keys) {
    const before = base[key];
    const after = draft[key];
    if (JSON.stringify(before ?? null) !== JSON.stringify(after ?? null)) {
      changes[key] = after;
    }
  }
  // revision / agent_id 不可经 payload 改 (后端 Fix-66 会剥离), 前端先去掉避免误导 diff。
  delete changes.revision;
  delete changes.agent_id;
  return changes;
}

export function useConfigTransaction<T extends Record<string, unknown>>(
  options: ConfigTransactionOptions<T>,
): ConfigTransaction<T> {
  const { base, revision, validate, submit, reload, onApplied } = options;
  const isHighImpact = options.isHighImpact ?? configApi.isHighImpactChange;

  const [draft, setDraftState] = useState<T>(base);
  const [phase, setPhase] = useState<TransactionPhase>("idle");
  const [validation, setValidation] = useState<ConfigValidateResult | null>(null);
  const [changes, setChanges] = useState<ConfigDiffChange[]>([]);
  const [applyResult, setApplyResult] = useState<ConfigApplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<ConfigTransaction<T>["conflict"]>(null);

  const localChanges = useMemo(() => computeLocalChanges(base, draft), [base, draft]);
  const isDirty = Object.keys(localChanges).length > 0;
  const highImpact = useMemo(() => changes.filter(isHighImpact), [changes, isHighImpact]);
  const busy = phase === "validating" || phase === "diffing" || phase === "committing";

  const setDraft = useCallback((next: T) => {
    setDraftState(next);
    setPhase((current) => (current === "applied" || current === "conflict" ? "editing" : current === "idle" ? "editing" : current));
    setApplyResult(null);
    setConflict(null);
  }, []);

  const patchField = useCallback(
    <K extends keyof T>(key: K, value: T[K]) => {
      setDraftState((current) => ({ ...current, [key]: value }));
      setPhase((current) => (current === "idle" || current === "applied" || current === "conflict" ? "editing" : current));
      setApplyResult(null);
      setConflict(null);
    },
    [],
  );

  const runValidate = useCallback(async (): Promise<boolean> => {
    if (!validate) {
      setValidation(null);
      return true;
    }
    setPhase("validating");
    setError(null);
    try {
      const result = await validate(draft);
      setValidation(result);
      if (!result.valid) {
        setPhase("invalid");
        return false;
      }
      return true;
    } catch (err) {
      setError(isApiError(err) ? `${err.message} (${err.code})` : String(err));
      setPhase("failed");
      return false;
    }
  }, [validate, draft]);

  const runDiff = useCallback(async (): Promise<ConfigDiffChange[]> => {
    setPhase("diffing");
    setError(null);
    try {
      const result: ConfigDiffResult = await configApi.diffConfig(
        base as Record<string, unknown>,
        draft as Record<string, unknown>,
      );
      setChanges(result.changes);
      return result.changes;
    } catch (err) {
      setError(isApiError(err) ? `${err.message} (${err.code})` : String(err));
      setPhase("failed");
      return [];
    }
  }, [base, draft]);

  const prepare = useCallback(async (): Promise<"ready" | "confirm" | "blocked"> => {
    if (!isDirty) {
      setError("没有任何字段变更 (提交会被后端以 400 no effective changes 拒绝)。");
      setPhase("failed");
      return "blocked";
    }
    const valid = await runValidate();
    if (!valid) return "blocked";
    const diff = await runDiff();
    if (diff.length === 0) {
      setError("服务端 diff 为空: 变更没有实际效果。");
      setPhase("failed");
      return "blocked";
    }
    const impactful = diff.filter(isHighImpact);
    if (impactful.length > 0) {
      setPhase("confirming");
      return "confirm";
    }
    setPhase("confirming");
    return "ready";
  }, [isDirty, runValidate, runDiff, isHighImpact]);

  const commit = useCallback(async (): Promise<boolean> => {
    setPhase("committing");
    setError(null);
    try {
      const result = await submit(localChanges, revision);
      setApplyResult(("applied" in result ? result : { applied: [], reload_required: [], restart_required: [], reloaded_agents: [], reload_errors: {}, ...result }) as ConfigApplyResult);
      setPhase("applied");
      setConflict(null);
      setChanges([]);
      onApplied?.(result);
      return true;
    } catch (err) {
      if (isApiError(err) && err.kind === "conflict") {
        setConflict({ expectedRevision: revision, serverRevision: err.currentRevision });
        setPhase("conflict");
        setError(err.message);
        return false;
      }
      setError(isApiError(err) ? `${err.message} (${err.code})` : String(err));
      setPhase("failed");
      return false;
    }
  }, [submit, localChanges, revision, onApplied]);

  const adoptServerVersion = useCallback(async () => {
    setError(null);
    try {
      const latest = await reload();
      setDraftState(latest);
      setConflict(null);
      setChanges([]);
      setValidation(null);
      setPhase("editing");
    } catch (err) {
      setError(isApiError(err) ? `${err.message} (${err.code})` : String(err));
      setPhase("failed");
    }
  }, [reload]);

  const rebaseOnServer = useCallback(async () => {
    setError(null);
    try {
      const latest = await reload();
      // 把"我改过的字段"重放到服务器最新版本上, 其余字段以服务器为准 ——
      // 既不静默覆盖别人的修改, 也不丢自己的编辑。
      setDraftState({ ...latest, ...localChanges } as T);
      setConflict(null);
      setChanges([]);
      setValidation(null);
      setPhase("editing");
    } catch (err) {
      setError(isApiError(err) ? `${err.message} (${err.code})` : String(err));
      setPhase("failed");
    }
  }, [reload, localChanges]);

  const reset = useCallback(() => {
    setDraftState(base);
    setPhase("idle");
    setChanges([]);
    setValidation(null);
    setApplyResult(null);
    setError(null);
    setConflict(null);
  }, [base]);

  const closeResult = useCallback(() => {
    setApplyResult(null);
    setPhase((current) => (current === "applied" ? "idle" : current));
  }, []);

  return {
    phase,
    draft,
    setDraft,
    patchField,
    isDirty,
    localChanges,
    validation,
    changes,
    highImpact,
    applyResult,
    error,
    conflict,
    busy,
    runValidate,
    runDiff,
    prepare,
    commit,
    adoptServerVersion,
    rebaseOnServer,
    reset,
    closeResult,
  };
}
