/** API 领域响应类型 (依据后端路由实现逐个核对建模)。
 *
 * 为什么需要这一层: 后端控制面路由的返回注解是 `dict` / `list[dict]`,
 * 导出到 openapi.json 后响应体是宽松的 `{[key: string]: unknown}` (契约基线
 * 只保证 path/method/参数形状)。前端在此按实际实现显式建模, 让页面拿到强类型;
 * 端点模块统一在 `unwrap<T>()` 一处断言, 页面不再散落 `as`。
 *
 * 口径备注 (与 v1 内置 WebUI 的差异, 属 v1 缺陷, 本项目按后端真实形状实现):
 * - `/usage/models/summary`、`/usage/models/events`、`/subagent-runs`、
 *   `/identity/conflicts`、`/workflows`、`/tenants` 返回**数组**, 不是 `{key: []}`;
 * - `/plugins/failed` 的 `failures` 是 **对象** (name → 错误信息), 不是数组;
 * - `estimated_cost` / `estimated_cost_sum` 是**字符串** (Decimal 序列化) 或 null,
 *   展示前必须显式转数字, 未知价格保持 null (SPEC §8.5 不伪造成本)。
 */

// ── 通用 ────────────────────────────────────────

/** 后端统一错误体 (CONTROL_PLANE_SPEC §3.6)。 */
export interface ErrorDetail {
  code?: string;
  message?: string;
  current_revision?: number;
}

/** 简单状态回执 (`{"status": "updated"}` 一类)。 */
export interface StatusResult {
  status: string;
  [key: string]: unknown;
}

// ── 健康 / 认证 / setup ─────────────────────────

export type LlmHealth = "configured" | "stub" | "not_configured" | "unknown" | string;

export interface HealthResponse {
  status: "ok" | "degraded" | string;
  subsystems: {
    agents: { total: number; running: number };
    llm: LlmHealth;
    channels: string[];
    control: { enabled: boolean; host: string; port: number };
  };
  setup_required: boolean;
}

export interface SetupStatus {
  setup_required: boolean;
}

export interface SetupCompleteResult {
  status: string;
  setup_required: boolean;
}

export interface SessionLoginResult {
  status: string;
}

// ── Agent ───────────────────────────────────────

export interface AgentSummary {
  agent_id: string;
  status: string;
}

/** AgentConfig 全量 (dataclass asdict; 敏感键值可能是脱敏哨兵)。 */
export interface AgentConfig {
  agent_id: string;
  display_name: string;
  enabled: boolean;
  persona: Record<string, unknown>;
  gating: Record<string, unknown>;
  memory_namespace: string;
  llm: Record<string, unknown> | null;
  trigger_words: string[];
  mesh_role: string;
  plugins_allow: string[];
  plugins_deny: string[];
  tools_policy: Record<string, string>;
  commands_allow: string[];
  mcp_servers: string[];
  model_capabilities_allow: string[];
  conversation: Record<string, unknown>;
  revision: number;
}

export interface AgentPatchResult {
  agent_id: string;
  status: string;
  revision: number;
}

export interface PluginMatrix {
  plugins_allow: string[];
  plugins_deny: string[];
}

// ── 路由 / Link ─────────────────────────────────

export interface ChannelBinding {
  platform: string;
  agent_id: string;
  group_id: string | null;
  user_id: string | null;
}

export interface RoutingRules {
  bindings: ChannelBinding[];
  default_agents: Record<string, string>;
}

export interface InterAgentLink {
  from_agent: string;
  to_agent: string;
  direction: "both" | "oneway" | string;
  enabled: boolean;
  permissions: string[];
  visible_memory_scopes: string[];
  max_context_messages: number;
}

// ── 插件 ────────────────────────────────────────

export interface LoadedPlugin {
  name: string;
  isolated: boolean;
}

export interface LoadedPluginsResult {
  plugins: LoadedPlugin[];
  total: number;
}

/** 市场清单条目 (data/plugin_marketplace.jsonc + 远程清单合并, 字段宽松)。 */
export interface MarketplacePlugin {
  name: string;
  description?: string;
  version?: string;
  author?: string;
  download_url?: string;
  repo_url?: string;
  homepage?: string;
  [key: string]: unknown;
}

export interface MarketplaceResult {
  plugins: MarketplacePlugin[];
  total: number;
}

/** 失败清单: name → 错误信息 (进程内, 重启清空)。 */
export interface FailedPluginsResult {
  failures: Record<string, string>;
  total: number;
}

export interface PluginActionResult {
  status: string;
  /** 运行中 Agent 的工具/命令/注入器同步结果 (agent_id → 名称列表)。 */
  sync: Record<string, string[]>;
}

/** 安装源 (POST /plugins/install 的 body; 后端接受 `{source: {...}}` 或裸 source)。 */
export type PluginInstallSource =
  | { type: "market"; name: string }
  | { type: "git"; repo_url: string; name?: string }
  | { type: "url"; url: string; name?: string }
  | { type: "upload"; name: string; zip_b64: string }
  | { type: string; name?: string; [key: string]: unknown };

// ── Provider / 模型 / 制品 ──────────────────────

export interface ProviderSummary {
  provider_id: string;
  model_id: string;
}

export interface ModelDescriptor {
  provider_id: string;
  model_id: string;
  operations: string[];
  modalities_in: string[];
  modalities_out: string[];
  cost_tier: string;
  latency_tier: string;
}

export interface ArtifactMeta {
  artifact_id: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  duration_seconds: number | null;
  created_at: number;
  expires_at: number;
  uri: string;
}

export interface ProviderTestResult {
  provider_id: string;
  status: string;
}

// ── 用量与成本 ──────────────────────────────────

/** 聚合行: 分组列 + 度量列。estimated_cost_sum 为字符串 (6 位小数) 或 null。 */
export interface UsageSummaryRow {
  provider?: string | null;
  model?: string | null;
  agent_id?: string | null;
  session_id?: string | null;
  modality?: string | null;
  operation?: string | null;
  status?: string | null;
  fallback?: boolean | null;
  time_bucket?: string | null;
  request_count: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cache_read_tokens?: number | null;
  cache_write_tokens?: number | null;
  reasoning_tokens?: number | null;
  audio_input_tokens?: number | null;
  audio_output_tokens?: number | null;
  estimated_cost_sum: string | null;
}

/** 单次物理请求明细 (model_usage_events 行)。 */
export interface UsageEventRow {
  event_id: string;
  trace_id: string | null;
  request_id: string | null;
  agent_id: string | null;
  session_id: string | null;
  provider: string | null;
  model: string | null;
  modality: string | null;
  operation: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  input_units: number | null;
  output_units: number | null;
  unit_name: string | null;
  estimated_cost: string | null;
  currency: string | null;
  pricing_version: string | null;
  latency_ms: number | null;
  status: string | null;
  fallback_from: string | null;
  created_at: number;
  [key: string]: unknown;
}

export type UsageGroupBy =
  | "provider"
  | "model"
  | "agent_id"
  | "session_id"
  | "modality"
  | "operation"
  | "status"
  | "fallback";

// ── 会话 ────────────────────────────────────────

export interface SessionDto {
  session_id: string;
  agent_id: string;
  user_id: string;
  platform: string;
  group_id: string | null;
  is_group: boolean;
  state: string;
  created_at: number;
  last_active: number;
}

export interface SessionListResult {
  sessions: SessionDto[];
}

export interface SessionMessage {
  memory_id: string;
  content: string;
  created_at: number;
}

export interface SessionMessagesResult {
  messages: SessionMessage[];
}

// ── 记忆 ────────────────────────────────────────

export interface MemoryEpisode {
  id: string;
  session_id: string;
  user_id: string;
  content: string;
  summary: string | null;
  importance: number | null;
  created_at: number;
}

export interface MemoryProfile {
  person_id: string;
  name: string;
  profile_text: string | null;
  relationship_depth: number | null;
  interaction_count: number | null;
  first_seen: number | null;
  last_seen: number | null;
}

export interface MemoryJargon {
  word: string;
  meaning: string | null;
  context: string | null;
  usage_count: number | null;
  created_at: number | null;
}

/** 治理视图条目 (GET /memory/{agent}/items, 含软删)。 */
export interface MemoryItem {
  id: string;
  content: string;
  type: string;
  frozen: number;
  protected: number;
  deleted: number;
}

export interface MemoryItemsResult {
  ok: boolean;
  count: number;
  items: MemoryItem[];
}

export interface GovernanceResult {
  ok: boolean;
  detail: string;
}

// ── SubAgent / 审批 ─────────────────────────────

export interface TokenUsageDto {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface SubAgentRun {
  task_id: string;
  parent_agent_id: string;
  status: string;
  phase: string;
  started_at: number;
  updated_at: number;
  finished_at: number;
  tokens_used: number;
  tool_calls_used: number;
  error_code: string;
  error_summary: string;
  result_summary: string;
  evidence_refs: string[];
  usage: TokenUsageDto | null;
}

export interface SubAgentEvent {
  seq: number;
  event_type: string;
  timestamp: number;
  summary: string;
  tool_name: string;
}

export interface SubAgentEventsResult {
  task_id: string;
  events: SubAgentEvent[];
}

export interface ApprovalRequest {
  approval_id: string;
  session_key: string;
  tool_name: string;
  args_summary: string;
  created_at: number;
  elapsed_seconds: number;
}

export interface ApprovalDecisionRecord {
  session_key: string;
  seq: number;
  event_type: "tool.called" | "tool.outcome" | string;
  timestamp: number;
  payload: Record<string, unknown>;
}

// ── 配置编辑事务 ────────────────────────────────

export interface ConfigValidateResult {
  valid: boolean;
  errors: string[];
}

export interface ConfigDiffChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface ConfigDiffResult {
  changes: ConfigDiffChange[];
}

export interface GlobalConfigResult {
  config: Record<string, unknown>;
  revision: number;
}

/** PATCH /config/global 与 POST /config/global/reload 的应用结果 (§8.2 规则 6)。 */
export interface ConfigApplyResult {
  applied: string[];
  reload_required: string[];
  restart_required: string[];
  reloaded_agents: string[];
  reload_errors: Record<string, string>;
  revision?: number;
}

/** GET /config/schema: pydantic 生成的 JSON Schema (表单驱动前提)。 */
export interface JsonSchema {
  title?: string;
  type?: string;
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  $defs?: Record<string, JsonSchemaNode>;
  [key: string]: unknown;
}

export interface JsonSchemaNode {
  title?: string;
  description?: string;
  type?: string | string[];
  default?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchemaNode[];
  allOf?: JsonSchemaNode[];
  $ref?: string;
  items?: JsonSchemaNode;
  properties?: Record<string, JsonSchemaNode>;
  additionalProperties?: boolean | JsonSchemaNode;
  minimum?: number;
  maximum?: number;
  [key: string]: unknown;
}

// ── 审计 / 指标 / 日志 ──────────────────────────

export interface AuditEntry {
  timestamp: number;
  iso: string;
  actor: string;
  method: string;
  path: string;
  action: string;
  target: string;
  status_code: number;
  detail: string;
}

export interface MetricsSnapshot {
  counters: Record<string, number>;
  gauges: Record<string, number>;
  histograms: Record<string, { count: number; sum: number }>;
}

/** SSE /logs/tail 单条日志 (structlog event_dict + buffer 序号)。 */
export interface LogEntry {
  _seq: number;
  _ts: number;
  level?: string;
  logger?: string;
  event?: string;
  timestamp?: string | number;
  [key: string]: unknown;
}

export type LogLevel = "debug" | "info" | "warning" | "error" | "critical";

// ── Webhook / 租户 / 身份 / 工作流 ──────────────

/** GET /webhooks: event → url 列表。 */
export type WebhookSubscriptions = Record<string, string[]>;

export interface WebhookTriggerResult {
  event: string;
  /** url → "ok" / "failed: <error>"。 */
  delivered: Record<string, string>;
}

export interface TenantDto {
  tenant_id: string;
  organization_id: string;
  display_name: string;
  state: string;
  created_at: number;
  members: unknown[];
}

export interface IdentityConflict {
  conflict_id: string;
  person_id: string;
  /** 后端直出 candidates_json (JSON 字符串)。 */
  candidates: string;
  highest_confidence: number;
  created_at: number;
  resolved: number;
}

export interface WorkflowDto {
  workflow_id: string;
  name: string;
  status: string;
  stages: number;
}
