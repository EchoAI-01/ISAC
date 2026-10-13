/** 配置编辑事务端点 (routes_config.py, CONTROL_PLANE_SPEC §8.2 / §3.7)。
 *
 * 事务顺序 (F2 验收):
 *   GET resource + schema + revision → 表单编辑 → POST /config/validate
 *   → POST /config/diff → 用户确认高影响变更 → PATCH (If-Match: revision)
 *   → 展示 applied / reload_required / restart_required (规则 6: 不假装热更成功)
 *
 * 乐观锁: revision 不符 → 409 CONFIG_CONFLICT (含 current_revision);
 * 前端必须展示服务器版本与本地变更, 不静默覆盖 (规则 3)。
 *
 * 敏感键: GET 回显为脱敏哨兵 `__ISAC_REDACTED__`; 回传哨兵 = 未修改
 * (后端 _strip_redacted / _restore_redacted 会剥离), 前端只允许"设置/替换/清除"。
 */

import { client, unwrap } from "./client";
import type {
  AgentConfig,
  ConfigApplyResult,
  ConfigDiffChange,
  ConfigDiffResult,
  ConfigValidateResult,
  GlobalConfigResult,
  JsonSchema,
} from "./types";

/** AgentConfig 字段校验 (不落盘)。 */
export function validateConfig(candidate: Partial<AgentConfig>): Promise<ConfigValidateResult> {
  return unwrap<ConfigValidateResult>(
    client.POST("/api/v1/config/validate", { body: candidate }),
    "/api/v1/config/validate",
  );
}

/** 字段级 diff 预览 (不落盘)。 */
export function diffConfig(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): Promise<ConfigDiffResult> {
  return unwrap<ConfigDiffResult>(
    client.POST("/api/v1/config/diff", { body: { before, after } }),
    "/api/v1/config/diff",
  );
}

/** 全局配置 JSON Schema (pydantic 生成, 表单驱动前提)。 */
export function getConfigSchema(): Promise<JsonSchema> {
  return unwrap<JsonSchema>(client.GET("/api/v1/config/schema"), "/api/v1/config/schema");
}

/** 有效全局配置 (敏感键脱敏) + override revision。 */
export function getGlobalConfig(): Promise<GlobalConfigResult> {
  return unwrap<GlobalConfigResult>(
    client.GET("/api/v1/config/global"),
    "/api/v1/config/global",
  );
}

/**
 * 全局配置部分更新 (深合并 + If-Match 乐观锁 + 热重载)。
 *
 * 叶值 `null` = 撤销该覆盖项 (回落 config.jsonc/默认); 空 patch → 400
 * INVALID_INPUT "no effective changes"。
 */
export function patchGlobalConfig(
  patch: Record<string, unknown>,
  ifMatch?: number,
): Promise<ConfigApplyResult> {
  return unwrap<ConfigApplyResult>(
    client.PATCH("/api/v1/config/global", {
      body: patch,
      ...(ifMatch === undefined ? {} : { headers: { "If-Match": String(ifMatch) } }),
    }),
    "/api/v1/config/global",
  );
}

/** 从磁盘重读 config.jsonc + override 并热应用 (手编配置免重启生效)。 */
export function reloadGlobalConfig(): Promise<ConfigApplyResult> {
  return unwrap<ConfigApplyResult>(
    client.POST("/api/v1/config/global/reload"),
    "/api/v1/config/global/reload",
  );
}

/** diff 变更里哪些属于"高影响" (SPEC §8.2 规则 2: 必须二次确认)。 */
const HIGH_IMPACT_FIELDS = new Set([
  "enabled",
  "plugins_allow",
  "plugins_deny",
  "tools_policy",
  "commands_allow",
  "mcp_servers",
  "memory_namespace",
  "llm",
  "model_capabilities_allow",
  "mesh_role",
]);

export function isHighImpactChange(change: ConfigDiffChange): boolean {
  if (HIGH_IMPACT_FIELDS.has(change.field)) return true;
  // 嵌套节 (llm.* / gating.*) 里含凭据或能力开关的键同样按高影响处理。
  return /(api_key|secret|token|password|policy|allow|deny)/i.test(change.field);
}

/** 需要二次确认的变更子集 (确认对话框只列这些)。 */
export function highImpactChanges(changes: ConfigDiffChange[]): ConfigDiffChange[] {
  return changes.filter(isHighImpactChange);
}
