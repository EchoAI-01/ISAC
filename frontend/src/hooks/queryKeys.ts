/** TanStack Query 缓存键 (集中定义, 避免各页面自造字符串导致失效不彻底)。
 *
 * 约定: 键的第一段是域名, 与侧栏十域一一对应; 带参数的键把参数放末位,
 * 这样 `invalidateQueries({ queryKey: queryKeys.agents.all })` 能一次清全域。
 */

export const queryKeys = {
  health: ["health"] as const,
  setupStatus: ["setup-status"] as const,
  metrics: ["metrics"] as const,
  prometheusText: ["metrics", "prometheus"] as const,

  agents: {
    all: ["agents"] as const,
    list: () => ["agents", "list"] as const,
    detail: (agentId: string) => ["agents", "detail", agentId] as const,
    config: (agentId: string) => ["agents", "config", agentId] as const,
    pluginMatrix: (agentId: string) => ["agents", "plugin-matrix", agentId] as const,
    subagentRuns: (agentId: string) => ["agents", "subagent-runs", agentId] as const,
  },

  routing: {
    all: ["routing"] as const,
    rules: () => ["routing", "rules"] as const,
    links: () => ["routing", "links"] as const,
  },

  plugins: {
    all: ["plugins"] as const,
    loaded: () => ["plugins", "loaded"] as const,
    marketplace: (refresh: boolean) => ["plugins", "marketplace", refresh] as const,
    failed: () => ["plugins", "failed"] as const,
  },

  providers: {
    all: ["providers"] as const,
    list: () => ["providers", "list"] as const,
    models: () => ["providers", "models"] as const,
  },

  artifacts: {
    all: ["artifacts"] as const,
    list: () => ["artifacts", "list"] as const,
  },

  usage: {
    all: ["usage"] as const,
    summary: (query: unknown) => ["usage", "summary", query] as const,
    events: (query: unknown) => ["usage", "events", query] as const,
    timeseries: (query: unknown) => ["usage", "timeseries", query] as const,
  },

  sessions: {
    all: ["sessions"] as const,
    list: (agentId?: string) => ["sessions", "list", agentId ?? "*"] as const,
    detail: (sessionId: string) => ["sessions", "detail", sessionId] as const,
    messages: (sessionId: string, limit: number) => ["sessions", "messages", sessionId, limit] as const,
  },

  memory: {
    all: ["memory"] as const,
    episodes: (agentId: string, limit: number) => ["memory", "episodes", agentId, limit] as const,
    profiles: (agentId: string) => ["memory", "profiles", agentId] as const,
    jargon: (agentId: string) => ["memory", "jargon", agentId] as const,
    items: (agentId: string, limit: number, offset: number) =>
      ["memory", "items", agentId, limit, offset] as const,
  },

  tasks: {
    all: ["subagent-runs"] as const,
    list: () => ["subagent-runs", "list"] as const,
    detail: (taskId: string) => ["subagent-runs", "detail", taskId] as const,
    events: (taskId: string, afterSeq: number, limit: number) =>
      ["subagent-runs", "events", taskId, afterSeq, limit] as const,
  },

  approvals: {
    all: ["approvals"] as const,
    pending: () => ["approvals", "pending"] as const,
    history: (limit: number) => ["approvals", "history", limit] as const,
  },

  config: {
    all: ["config"] as const,
    schema: () => ["config", "schema"] as const,
    global: () => ["config", "global"] as const,
  },

  audit: (query: unknown) => ["audit", query] as const,
  auditAll: ["audit"] as const,

  webhooks: {
    all: ["webhooks"] as const,
    list: (event?: string) => ["webhooks", "list", event ?? "*"] as const,
  },

  tenants: {
    all: ["tenants"] as const,
    list: (organization?: string) => ["tenants", "list", organization ?? "*"] as const,
    detail: (tenantId: string) => ["tenants", "detail", tenantId] as const,
  },

  identity: {
    all: ["identity"] as const,
    conflicts: () => ["identity", "conflicts"] as const,
  },

  workflows: {
    all: ["workflows"] as const,
    list: () => ["workflows", "list"] as const,
    detail: (workflowId: string) => ["workflows", "detail", workflowId] as const,
  },
} as const;
