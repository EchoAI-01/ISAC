# 页面实现契约 (F2 十域迁移)

> 给页面实现者 (人或 Agent) 的硬约束。**先读完本文件再写代码**; 违反任何一条都会被打回。
> 参考实现: `src/pages/dashboard/DashboardPage.tsx` (已完成的第一个域)。

---

## 0. 背景与事实源

- 后端 API 契约: `../docs/api/openapi.json` (68 路径, 已生成到 `src/api/openapi.d.ts`)。
- 页面信息架构: `../docs/CONTROL_PLANE_SPEC.md` §8.1 (十域) / §8.2 (配置编辑事务 7 条规则) /
  §8.3 (实时) / §8.4 (SubAgent 隐私) / §8.5 (前端工程与体验约束)。
- 端点使用文档: `../docs/api.md` (含"条件挂载"一节: 哪些端点在子系统未启用时不存在)。
- **不得**直接 `fetch`, **不得**手写 URL 字符串拼接端点: 一律经 `src/api/*.ts` 的封装函数
  (它们用 openapi-fetch 的 `client`, path/参数编译期校验)。
- 需要的端点若 `src/api/` 里没有封装, 可以在**自己的页面目录**下加一个薄封装
  (`import { client, unwrap } from "@/api/client"`), 但**不得修改** `src/api/`、`src/components/`、
  `src/hooks/`、`src/app/` 下的共享文件 (多人并行会冲突)。缺什么就在自己目录里补什么。

---

## 1. 文件与命名

| 域 | 路由 | 入口文件 (default export) |
|----|------|--------------------------|
| Dashboard | `/` | `src/pages/dashboard/DashboardPage.tsx` ✅ 已完成 |
| Agents | `/agents`, `/agents/:agentId` | `src/pages/agents/AgentsPage.tsx`, `AgentDetailPage.tsx` |
| Channels & Routing | `/channels` | `src/pages/channels/ChannelsRoutingPage.tsx` |
| Providers & Models | `/providers` | `src/pages/providers/ProvidersPage.tsx` |
| Usage & Cost | `/usage` | `src/pages/usage/UsagePage.tsx` |
| Extensions | `/extensions` | `src/pages/extensions/ExtensionsPage.tsx` |
| Memory | `/memory` | `src/pages/memory/MemoryPage.tsx` |
| Sessions & Tasks | `/sessions` | `src/pages/sessions/SessionsTasksPage.tsx` |
| Logs & Audit | `/logs` | `src/pages/logs/LogsAuditPage.tsx` |
| System | `/system` | `src/pages/system/SystemPage.tsx` |

- 页面私有子组件放同目录 (`src/pages/<域>/components/*.tsx`), 不放进 `src/components/`。
- 一个文件 ≤ 400 行; 超了就拆子组件。
- 文件名 PascalCase, hook 文件 camelCase。

---

## 2. 可直接使用的共享件 (签名即事实, 不要臆造 props)

### 组件 (`src/components/`)

```ts
// Button.tsx
Button({ variant?: "primary"|"secondary"|"danger"|"ghost", size?: "md"|"sm",
         loading?: boolean, accessibleName?: string, ...ButtonHTMLAttributes })
Spinner({ className?, label? })

// Card.tsx
Card({ title?, subtitle?, actions?, flush?, footer?, className?, children, ...div属性(不含 title) })
PageHeader({ title, description?, actions? })
Callout({ tone?: "info"|"warning"|"danger"|"success", title?, children?, className? })

// Badge.tsx
Badge({ tone?: "neutral"|"success"|"danger"|"warning"|"info"|"primary", dot?, title?, children })
agentStatusTone(status: string): BadgeTone
statusTone(status: string): BadgeTone

// Table.tsx  —— 小屏自动转摘要卡片 (td[data-label])
interface Column<T> { key: string; header: ReactNode; label?: string;
                      render: (row: T, index: number) => ReactNode;
                      className?: string; align?: "left"|"right";
                      sort?: "ascending"|"descending"|"none"; onSort?: () => void }
Table<T>({ columns, rows, rowKey: (row, index) => string, ariaLabel: string,   // ariaLabel 必填
           caption?, empty?, compact?, responsive?, onRowClick?, className? })

// QueryState.tsx —— 五态包装器, 所有读查询都必须经它
QueryState<T>({ query, children: (data: T) => ReactNode, isEmpty?, empty?,
                loadingLabel?, showStale?, staleLabel? })

// StateViews.tsx
StateView({ variant, title, description?, actions?, icon? })
LoadingState({ label? }) / EmptyState({ title?, description?, actions? })
ErrorState({ title?, description?, onRetry?, retrying? })
PermissionDeniedState({ scope?, message?, title? })
UnavailableState({ title?, description?, configHint? })
ErrorBoundaryState({ error, onRetry?, retrying? })   // 按 ApiError.kind 自动选上面几种
unavailableHint(path?) / scopeHint(path?)

// Form.tsx
Field({ label, hint?, error?, required?, children, htmlFor? })
TextField({ label, hint?, error?, mono?, ...input属性 })
TextArea({ label, hint?, error?, mono?, ...textarea属性 })
SelectField({ label, hint?, error?, options: {value,label,disabled?}[], ...select属性 })
CheckboxField({ label, hint?, ...input属性 })
InlineFilter({ label, children })

// Inputs.tsx
Toolbar({ children, className? }) / ToolbarGroup({ label, children, htmlFor? })
SegmentedControl<T extends string>({ options: {value,label}[], value, onChange, ariaLabel })
TagInput({ values: string[], onChange, placeholder?, ariaLabel, allowWildcard?, suggestions? })
Pagination({ offset, limit, total?, hasMore?, onChange, pageSizeOptions?, onPageSizeChange?, ariaLabel? })
CopyButton({ value, label? })
JsonEditor({ value, onChange, onError?, label, hint?, rows?, id? })   // 只做 JSON 语法校验

// Tabs.tsx
Tabs({ items: TabItem[], value, onChange, ariaLabel, className? })
  TabItem = { value: string; label: ReactNode; count?: number; content: ReactNode;
              disabled?: boolean; disabledReason?: string }
Modal({ open, title, description?, onClose, footer?, wide?, children, initialFocus? })
ConfirmDialog({ open, title, impact, confirmLabel?, cancelLabel?, tone?, requireText?,
                onConfirm, onCancel, loading?, children? })

// DataDisplay.tsx
KeyValue({ items: {term, value}[] })
CodeBlock({ children, maxHeight?, ariaLabel, testId? })
Stat({ label, value, meta?, tone?: "default"|"success"|"warning"|"danger", testId? })
StatGrid({ children })
BarChart({ rows: {label,value,display?}[], ariaLabel, formatValue? })  // 自带文本表格替代
Timeline({ items: {time,title,description?,muted?}[], ariaLabel })
ShortId({ value, max? })

// DiffTable.tsx
DiffTable({ changes: ConfigDiffChange[], isHighImpact?, caption? })
formatDiffValue(value: unknown): string

// Toast.tsx
useToast() → { success(title, desc?), error(title, desc?), warning(...), info(...), push, dismiss }
```

### 读查询 (`src/hooks/queries.ts`)

`useHealth` `useSetupStatus` `useMetricsSnapshot` `useAudit(query)` `useAgents`
`useAgentConfig(agentId?)` `usePluginMatrix(agentId?)` `useRoutingRules` `useLinks`
`useLoadedPlugins` `useMarketplace(refresh?)` `useFailedPlugins` `useProviders` `useModels`
`useArtifacts` `useUsageSummary(query)` `useUsageEvents(query)` `useUsageTimeseries(query)`
`useSessions(agentId?)` `useSessionMessages(sessionId?, limit?)` `useMemoryEpisodes(agentId?, limit?)`
`useMemoryProfiles(agentId?)` `useMemoryJargon(agentId?)` `useMemoryItems(agentId?, limit?, offset?)`
`useSubAgentRuns` `useAgentSubAgentRuns(agentId?)` `useSubAgentEvents(taskId?, afterSeq?, limit?)`
`useApprovals` `useApprovalHistory(limit?)` `useConfigSchema` `useGlobalConfig`
`useWebhooks(event?)` `useTenants(org?)` `useIdentityConflicts` `useWorkflows`

### 写操作 (`src/hooks/mutations.ts`)

`useCreateAgent` `useAgentLifecycle()` → `{start, stop, destroy}` (destroy 变量
`{id, keepMemory}`) `usePatchAgent()` (变量 `{agentId, patch, ifMatch?}`) `usePutPluginMatrix(agentId)`
`usePutRoutingRules` `useAddLink` `useRemoveLink` `useInstallPlugin` `useReloadPlugin`
`useUninstallPlugin` `useRetryPlugin` `useTestProvider` `useDeleteArtifact`
`useGovernanceAction(agentId)` (变量 `{action, itemId, content?}`) `useCancelSubAgentRun`
`useDecideApproval` (变量 `{approvalId, decision}`) `usePatchGlobalConfig` (变量 `{patch, ifMatch?}`)
`useReloadGlobalConfig` `useSubscribeWebhook` `useUnsubscribeWebhook` `useTriggerAutomation`
`useCreateTenant` `useDeleteTenant` `useTenantMembers(tenantId)` → `{add, remove}`
`useBindIdentity` `useResolveConflict` `useStartWorkflow`

调用形态: `const m = useCreateAgent(); m.mutate(vars)` 或 `m.mutateAsync(vars)`;
`m.isPending` 给按钮 loading。**mutation 已内置 Toast 与缓存失效, 页面不要重复弹提示**。

### URL 状态 (`src/hooks/useUrlState.ts`)

`useUrlString(key, fallback?)` `useUrlNumber(key, fallback)` `useUrlEnum(key, allowed[], fallback)`
`useUrlBoolean(key, fallback?)` `useUrlTab(allowed[], fallback)`
→ 全部返回 `[value, setValue]`, 写入 `?key=value` (等于 fallback 时从 URL 删除)。

### 配置编辑事务 (`src/features/config/`)

```ts
useConfigTransaction<T extends Record<string, unknown>>({
  base: T, revision: number|undefined,
  validate?: (candidate: T) => Promise<ConfigValidateResult>,   // AgentConfig 传, 全局配置可省
  submit: (patch, ifMatch?) => Promise<ConfigApplyResult | {revision?: number}>,
  reload: () => Promise<T>,
  isHighImpact?, onApplied?
})
→ { phase, draft, setDraft, patchField, isDirty, localChanges, validation, changes,
    highImpact, applyResult, error, conflict, busy, runValidate, runDiff, prepare,
    commit, adoptServerVersion, rebaseOnServer, reset, closeResult }

// 配套展示件 (ConfigTransactionPanels.tsx)
TransactionToolbar({ transaction, revision, onPrepare, onReset, prepareLabel?, extra? })
ValidationPanel({ validation })
DiffPanel({ changes, isHighImpact?, title? })
ConfirmChangesDialog({ open, changes, highImpact, busy?, onConfirm, onCancel, title?, isHighImpact? })
ConflictPanel({ conflict, localChanges, onAdoptServer, onRebase, busy? })
ApplyResultPanel({ result, onClose? })
```

### SSE (`src/hooks/useSse.ts` + `src/api/system.ts` / `src/api/events.ts`)

```ts
useSse<T>({ create: (handlers) => SseConnection, enabled?, maxItems?, flushIntervalMs? })
→ { items, phase, paused, error, totalReceived, dropped, lastEventId, lastHeartbeatAt,
    pause, resume, clear, trackLastEventId }

tailLogs({ level?, heartbeatSeconds?, maxChunks?, onEntry, onOpen?, onError?, onClose?,
           onHeartbeat?, lastEventId?, signal?, maxRetries? }): SseConnection
streamEvents({ heartbeatSeconds?, maxChunks?, onEvent, ... }): SseConnection
LOG_LEVELS / EVENT_CATALOG / PUBLIC_EVENT_TYPES / WEBHOOK_EVENT_CATALOG / WEBHOOK_EVENTS_WIRED
```

### 格式化 (`src/lib/format.ts`)

`formatTimestamp(sec)` `formatClockTime(sec)` `formatIsoDate(sec)` `formatRelative(sec, nowSec)`
`formatInt(n)` `formatTokens(n)` `formatCost(usd, digits?)` `formatEstimatedCost(usd)`
`formatBytes(n)` `formatDuration(sec)` `truncate(s, max?)` `display(v)` `prettyJson(v)`
`src/api/usage.ts::parseCost(str|null) → number|null` (未知价格返回 null, **不得**当 0)

---

## 3. 硬规则 (逐条可检查)

1. **零假数据**: 任何数字/列表都必须来自真实端点。端点未挂载 (404 无业务 code) →
   `<UnavailableState configHint={unavailableHint(path)}>`; 权限不足 (403) →
   `<PermissionDeniedState scope={scopeHint(path)}>`。**不许**用 `try/catch → 空数组`
   把这两种情况伪装成"暂无数据"(v1 内置 WebUI 就是这么错的)。
2. **所有读查询都经 `<QueryState>`** (或显式渲染 `ErrorBoundaryState`), 保证
   loading / empty / error / stale / permission-denied 五态齐备 (§8.5)。
3. **筛选、分页、tab 一律写 URL** (用 `useUrlState` 系列), 刷新与分享不丢状态。
4. **写操作二次确认**: 删除 Agent / 删租户 / 删制品 / 清记忆 / 卸载插件 / 解绑 /
   `keep_memory=false` / 高影响配置变更 → 必须 `<ConfirmDialog>` 且 `impact` 写清后果;
   不可逆的 (删 Agent、删租户、卸载插件) 用 `requireText`。
5. **敏感字段**: `__ISAC_REDACTED__` 哨兵 (用 `isRedacted()` 判断) 只显示"已配置",
   提供"替换/清除"两种操作; 永不回显、永不打印、永不写日志。凭据不得进 localStorage。
6. **成本/Token 必须带单位与"估算"标识**; 价格未知显示 `—` (用 `parseCost` + `formatCost`)。
7. **图表必须有文本/表格替代** → 用 `<BarChart>` (自带表格), 不要自己画 canvas/svg。
8. **a11y (WCAG 2.1 AA)**: 表格给 `ariaLabel`; 图标按钮给 `accessibleName`;
   状态不只靠颜色 (配 `Badge` 文本或 `sr-only`); 对话框用现成 `Modal`/`ConfirmDialog`
   (已做焦点陷阱与 Esc); 不要新增 `onClick` 的 `<div>`。
9. **时间戳口径**: 后端一律 epoch **秒** (float)。用 `format*` 系列, 不要自己 `new Date(x)`。
10. **响应形状**: 见 `src/api/types.ts` 顶部注释。特别注意
    `/usage/models/*`、`/subagent-runs`、`/identity/conflicts`、`/workflows`、`/tenants`
    返回**数组**; `/plugins/failed` 的 `failures` 是 **对象** (name → 错误信息)。
11. **e2e 钩子**: 关键元素加 `data-testid`, 命名 `<域>-<用途>`, 例如
    `agents-table`、`agents-create-submit`、`logs-console`、`plugins-install-submit`、
    `config-diff-panel`、`config-conflict-panel`。表格容器用 `data-testid="<域>-table"`。
12. **不新建全局状态**; 服务端状态一律 TanStack Query, 客户端状态用 `useState` / URL。
13. **不用 `any`** (确有必要写 `unknown` + 收窄); 不用 `@ts-ignore` / `eslint-disable`。
14. **中文文案**, 面向运维者; 术语保留英文原词 (scope / revision / SSE / Agent)。
15. 页面顶部一律 `<PageHeader title=… description=<§8.1 的核心内容原文>> actions=… />`。

---

## 4. 各域必须实现的内容

### Agents (`/agents`, `/agents/:agentId`)
- 列表: agent_id / 状态 Badge / 快捷操作 (启动/停止/详情/销毁), 创建表单 (agent_id +
  display_name + trigger_words `TagInput`)。**必须提示**: 创建走受限默认模板,
  能力字段 (tools_policy / plugins_allow / plugins_deny / commands_allow / mcp_servers)
  会被后端丢弃, 需创建后在详情页 PATCH 显式授予 (routes_agents `restricted_config_from_payload`)。
- 销毁: `keep_memory` 开关 + 说明 (false 会清 episodes/profiles/jargon + 向量库 + graph 边;
  `memory_namespace=shared` 时后端拒绝清理) → `requireText={agentId}`。
- 详情页 tabs: **配置** (完整配置编辑事务, 见下) / **插件矩阵** (allow/deny `TagInput`,
  PUT `/agents/{id}/plugins`) / **子任务** (`useAgentSubAgentRuns`) / **记忆概览** (跳 Memory 域)。
- 配置 tab 必须覆盖 AgentConfig 全字段 (见 `src/api/types.ts::AgentConfig`):
  身份 (display_name/enabled/memory_namespace/mesh_role/trigger_words)、
  能力 (plugins_allow/deny、tools_policy 四档 allow|restricted|ask|deny、commands_allow、
  mcp_servers、model_capabilities_allow)、LLM (dict, 含 api_key 哨兵处理)、
  persona / gating / conversation (JSON 编辑器 + 语法校验)。
  事务顺序: `prepare()` (校验 + diff) → 有高影响变更走 `ConfirmChangesDialog` → `commit()`
  → 409 走 `ConflictPanel` (两个按钮都要能点) → 成功展示 `ApplyResultPanel`。
  `tools_policy` 非法档位后端会 400 INVALID_CONFIG, 要把错误原文显示出来。

### Channels & Routing (`/channels`)
- Channel 状态来自 `/health.subsystems.channels`; **必须明确说明** `/channels*` REST 端点
  后端未实现 (CONTROL_PLANE_SPEC §3.3 状态注), 绑定能力目前仅 MCP 工具
  (`channel_bind_agent` / `channel_unbind_agent`) 提供, 不要做一个点了没反应的"绑定"按钮。
- 路由规则: bindings 表 (platform / agent_id / group_id / user_id) 增删改 + default_agents
  (platform → agent_id) 编辑, 整体 `PUT /routing/rules` (覆盖式, 提交前显示将覆盖成什么)。
- 互联 Link: 列表 (from/to/direction/enabled/permissions/visible_memory_scopes/
  max_context_messages) + 创建 + 删除 (`DELETE /links?from_agent&to_agent`)。
  创建表单要说明 permissions 为空 = notify/handoff/memory_query 全拒 (deny-by-default),
  仅 ask 可用。
- mesh_role 语义 (primary/observer/candidate) 用文字说明, 值来自 AgentConfig。

### Providers & Models (`/providers`)
- Provider 列表 (provider_id / model_id) + 连通性测试按钮 (写审计)。
- 模型目录表: provider / model / operations / modalities_in / modalities_out / cost_tier /
  latency_tier, 支持按 provider、operation、cost_tier 筛选 (URL)。
- 制品表: artifact_id (ShortId + CopyButton) / kind / mime / size (formatBytes) /
  duration / created_at / expires_at (过期标红) + 删除 (二次确认)。

### Usage & Cost (`/usage`)
- 时间范围 (`from`/`to`, 用 SegmentedControl 1h/24h/7d/30d + 自定义) 与
  provider/model/agent_id/modality/status 筛选, 全部写 URL。
- 汇总 tab: group_by 可多选 (provider/model/agent_id/session_id/modality/operation/status/fallback),
  表格 + `BarChart`; 成本列用 `parseCost` + `formatCost`, null 显示 `—` 并注明"价格未知"。
- 明细 tab: 分页 (limit/offset 写 URL), 列含 latency_ms、fallback_from (回退来源要显眼)、
  estimated_cost、pricing_version (价格快照可追溯, §九 Cost)。
- 趋势 tab: `/timeseries` bucket=hour|day, BarChart + 表格。
- 顶部注明: 数值含重试与回退; 成本为**估算**, 单位 USD, 时区为浏览器本地。

### Extensions (`/extensions`)  ← F4 插件市场在这里
- tabs: **插件** / **市场** / **失败** / **MCP** / **工作流**。
- 插件: `useLoadedPlugins` (name + isolated → "隔离子进程" / "宿主进程内") + reload / uninstall。
- 市场 (F4 验收): `useMarketplace(refresh)` 列表 (name/description/version/author) +
  一键安装 (`useInstallPlugin`, source `{type:"market", name}`) + 刷新清单按钮;
  另给"从 git / url 安装"表单 (`{type:"git", repo_url, name}` / `{type:"url", url, name}`)。
  `allow_install=false` 时写端点 404/405 → 渲染 `<UnavailableState configHint="control.plugins.allow_install = true">`。
  安装/重载结果要显示 `status` 与 `sync` (哪些运行中 Agent 同步到了哪些工具)。
- 失败 (F4 验收"失败插件可重试"): `useFailedPlugins` 的 `failures` 是对象 → 遍历
  `[name, message]`, 每行一个"重试"按钮 (`useRetryPlugin`), 并说明该清单进程内不持久化。
- MCP: 从 `useGlobalConfig()` 读 `config.mcp.servers` 只读展示 + 跳 System 域编辑
  (不要在 Extensions 里做第二套全局配置写路径)。
- 工作流: `useWorkflows` + 启动 (unavailable 时提示 `control.workflow.enabled=true`)。

### Memory (`/memory`)
- agent_id 选择器 (来自 `useAgents`, 写 URL `?agent=`) + 命名空间说明
  (默认 = agent_id, `shared` 为跨 Agent 共享)。
- tabs: **Episode** / **人物画像** / **行话** / **治理**。
- Episode: id/session/user/content/importance/created_at; content 默认截断 + 可展开。
- 画像: person_id/name/profile_text/relationship_depth/interaction_count/first_seen/last_seen。
- 行话: word/meaning/context/usage_count。
- 治理 (`useMemoryItems` + `useGovernanceAction`): 列表含 frozen/protected/deleted 标记,
  操作 = 冻结/保护/纠正(弹框输入 new_content)/删除(二次确认)/恢复。
  **结果按 `ok` 判定**: `ok=false` 时是"未生效"(warning) 而不是成功, detail 原样显示
  (受保护条目会被拒绝删除)。
- 分页 (limit/offset 写 URL)。

### Sessions & Tasks (`/sessions`)
- tabs: **会话** / **SubAgent 任务** / **审批 (HITL)**。
- 会话: 列表 (session_id ShortId/agent_id/user_id/platform/group_id/is_group/state/
  created_at/last_active) + agent 筛选 (URL) + 点选查看消息历史
  (`useSessionMessages`, 显示 memory_id/content/created_at, 分页)。
- SubAgent 任务 (§8.4): task_id / parent_agent_id / status / phase / 耗时 /
  tokens_used / tool_calls_used / error_code / error_summary / result_summary /
  evidence_refs 数量 + 详情 (事件时间线 `useSubAgentEvents`, 显示 seq/event_type/
  timestamp/summary/tool_name) + 取消 (`useCancelSubAgentRun`, 终态禁用,
  且结果按返回 status 判定 —— 已终态返回原终态不等于取消成功, 用 `isTerminalStatus`)。
  **不得**渲染 reasoning / 凭据 / 完整文件内容 (后端不返回, 也不要造字段)。
- 审批: pending 列表 (approval_id/session_key/tool_name/args_summary/created_at/
  elapsed_seconds) + 批准/拒绝 (`useDecideApproval`, 二次确认, 说明批准即放行高危工具) +
  决策留痕 (`useApprovalHistory`: session_key/seq/event_type/timestamp +
  payload 里的 decision/decider/reason, 用 CodeBlock 展示 payload)。
  审批门未接线 → unavailable 提示。

### Logs & Audit (`/logs`)  ← F3 在这里
- tabs: **实时日志** / **事件流** / **审计** / **Webhook**。tab 写 URL (`useUrlTab`)。
- 实时日志 (F3): `tailLogs` + `useSse`; level 筛选 (debug/info/warning/error/critical, 写 URL,
  改变时重连带新 level)、暂停/继续 (pause 记住 Last-Event-ID, resume 由服务端回放)、
  清空、行数上限 (maxItems, 默认 2000) 与 dropped 计数明示、连接状态 Badge
  (connecting/open/retrying/paused/error)、心跳时间。行渲染: 时间 (formatClockTime) +
  level (着色 class `console__line--<level>`) + logger + event + 其余字段 (可展开 JSON)。
  **必须**用 `useSse` 的批量刷新, 不要逐条 setState。
- 事件流 (F3): `streamEvents` + `useSse`; 事件名过滤 (URL)、payload 展开 (CodeBlock)、
  并**明确说明**后端现状: 桥接 EventBus 全部事件, 未登记 event_type 的落 `unknown`
  且仅 `"*"` 通配 scope 可见 (fail-closed), §8.3 目录里多数事件尚无生产者 ——
  窄 scope 看到空流是预期行为, 不是故障 (用 `EVENT_CATALOG` / `PUBLIC_EVENT_TYPES` 说明)。
- 审计: `useAudit({action, actor, path_prefix, limit})`, 筛选写 URL, 表格 +
  时间/操作者/方法/路径/动作/目标/状态码/detail; 说明 `tokens[]` 模式下需要 `"*"` 通配 scope。
- Webhook: 订阅清单 (`useWebhooks`, 返回 event → url[]; **URL 可能内嵌凭据, 展示时脱敏**
  query 与 userinfo, 参考后端 `redact_url` 语义) + 订阅/取消订阅 + 手动触发
  (`useTriggerAutomation`, 显示每个目标的投递结果) + 事件目录
  (`WEBHOOK_EVENT_CATALOG`, 用 `WEBHOOK_EVENTS_WIRED` 标出"已接线 / 目录预留") +
  注明 HMAC 签名后端未实现 (§5.3)。

### System (`/system`)
- tabs: **概览** / **全局配置** / **指标** / **多租户** / **身份归一** / **外观**。
- 概览: `/health` 全字段 (status + subsystems.agents/llm/channels/control) +
  setup_required 标记 + 版本 (从 `/api/v1/config/global` 或 health 无版本字段时注明"后端未暴露版本号",
  **不要**硬编码 "1.0.0" —— v1 内置 WebUI 就是这么假的) + 控制面 host/port。
- 全局配置 (F2 配置编辑事务): `useGlobalConfig()` 拿 `{config, revision}`,
  `useConfigSchema()` 拿 JSON Schema (22 顶层键, 每键有 description) → 一级节列表
  (按 schema properties 渲染标题 + description), 点开某节 → JSON 编辑器编辑该节 +
  事务 (`useConfigTransaction`, base=该节, submit=`usePatchGlobalConfig` 的 mutateAsync
  包成 `{patch: {[section]: value}, ifMatch}`, reload=重新 `getGlobalConfig` 取该节)。
  必须展示 `ApplyResultPanel` (applied / reload_required / restart_required /
  reloaded_agents / reload_errors), 并说明 control/channels/logging/debug/log_level
  属 restart_required。另给"从磁盘重读并热应用"按钮 (`useReloadGlobalConfig`) 与
  脱敏哨兵说明 (回传哨兵 = 未修改, 后端会剥离)。
- 指标: `useMetricsSnapshot()` counters/gauges/histograms 三段表格 (含 count/sum) +
  Prometheus 文本 (`getPrometheusText`) 用 CodeBlock + CopyButton。
- 多租户: 列表 (tenant_id/organization_id/display_name/state/created_at/members) +
  创建 + 删除 (`requireText`) + 成员增删; 说明绑定租户的 token 只能看到自己的租户,
  且创建会 403 TENANT_FORBIDDEN。
- 身份归一: `useIdentityConflicts` (candidates 是 **JSON 字符串**, 需 `JSON.parse` 后展示,
  解析失败原样显示) + 裁决 (`useResolveConflict`, 输入 person_id) + 手动绑定表单
  (`useBindIdentity`)。
- 外观: 主题切换 (auto/light/dark, 用 `src/lib/theme.ts` 的 readTheme/saveTheme/watchSystemTheme)。

---

## 5. 完成标准 (自己逐条核对后再交付)

1. `cd frontend && npx tsc --noEmit` 对**你负责的文件**零错误 (其他人的文件报错可忽略)。
2. `npx eslint <你的文件>` 零 error (warning 可留, 但要说明)。
3. 页面在"端点未挂载 / 403 / 空数据 / 有数据"四种情况下都有明确 UI (不能白屏)。
4. 所有写操作有 loading 态、成功/失败反馈 (mutation 自带 Toast, 不要重复弹)。
5. 筛选/分页/tab 刷新页面后保持 (因为在 URL 里)。
6. 关键交互元素有 `data-testid`。
7. 不修改共享文件; 不改后端。
