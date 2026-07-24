# ISAC 控制面规范

> 面向 Admin REST API、ISAC MCP Server、Webhooks 与自动化触发器的专项设计。
> 本文档补充 ARCHITECTURE.md 3.9 与 SPECIFICATION.md 4.4 / 4.5。

---

## 目录

- [一、设计目标](#一设计目标)
- [二、资源模型](#二资源模型)
- [三、REST API 规范](#三rest-api-规范)
- [四、MCP Server 工具规范](#四mcp-server-工具规范)
- [五、Webhook 规范](#五webhook-规范)
- [六、认证、权限与审计](#六认证权限与审计)
- [七、自动化安全默认值](#七自动化安全默认值)
- [八、WebUI v2 管理与观测](#八webui-v2-管理与观测)
- [九、验收标准](#九验收标准)
- [十、文档更新记录](#十文档更新记录)

---

## 一、设计目标

控制面独立于消息数据面，用于管理和自动化：

1. 创建、修改、启停、销毁 Agent。
2. 绑定 Channel 与 Agent，修改默认 Agent 和路由规则。
3. 管理 Agent 间 Link。
4. 管理插件、工具、命令、MCP 启用矩阵。
5. 暴露 MCP Server，让外部 Agent 系统管理 ISAC。
6. 提供 Webhook 事件推送与 `/automation/trigger` 自动化入口。
7. 所有副作用操作必须认证、授权、审计。

---

## 二、资源模型

| 资源 | 路径 | 说明 |
|------|------|------|
| AgentResource | `/agents/{id}` | Agent 配置与生命周期 |
| ChannelResource | `/channels/{platform}` | IM 连接状态与配置摘要 |
| BindingResource | `/channels/{platform}/agents/{id}` | Channel-Agent 绑定 |
| RoutingRulesResource | `/routing/rules` | 路由规则与默认 Agent |
| InterAgentLinkResource | `/links` | Agent 互联 ACL |
| PluginPolicyResource | `/agents/{id}/plugins` | 插件启用矩阵 |
| ToolPolicyResource | `/agents/{id}/tools` | 工具权限策略 |
| MCPPolicyResource | `/agents/{id}/mcp` | MCP Server 启用策略 |
| WebhookSubscription | `/webhooks/{id}` | Webhook 订阅 |
| AuditEvent | `/audit/events` | 审计事件 |
| ModelUsageResource | `/usage/models` | 模型请求、Token/计量单位与成本聚合 |
| ProviderResource | `/providers/{id}` | Provider 配置摘要、模型能力与健康状态 |
| ModelResource | `/models/{provider}/{model}` | 模态、operation、限制、成本/延迟层级与健康状态 |
| ArtifactResource | `/artifacts/{id}` | 多模态生成结果的元数据、权限与生命周期 |

---

## 三、REST API 规范

基础地址：`http://127.0.0.1:8765/api/v1`

认证：`Authorization: Bearer <control.api_token>`

### 3.1 Agent

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agents` | 创建 Agent |
| GET | `/agents` | 列出 Agent |
| GET | `/agents/{id}` | 获取 Agent |
| PATCH | `/agents/{id}` | 修改 Agent 配置 |
| DELETE | `/agents/{id}` | 销毁 Agent |
| POST | `/agents/{id}/start` | 启动 Agent |
| POST | `/agents/{id}/stop` | 停止 Agent |

创建请求：

```json
{
    "agent_id": "tech_agent",
    "display_name": "技术 Agent",
    "trigger_words": ["/tech"],
    "persona": {"style": "technical"},
    "memory_namespace": "tech_agent",
    "plugins_allow": ["search", "weather"],
    "tools_policy": {"bash": false},
    "mcp_servers": []
}
```

响应：

```json
{
    "agent_id": "tech_agent",
    "status": "stopped",
    "created": true
}
```

### 3.2 Routing

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/routing/rules` | 获取路由规则 |
| PUT | `/routing/rules` | 覆盖路由规则 |
| PATCH | `/routing/defaults/{platform}` | 设置平台默认 Agent |

### 3.3 Channel Binding

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/channels` | 列出 Channel |
| POST | `/channels/{platform}/agents/{agent_id}` | 绑定 Agent |
| DELETE | `/channels/{platform}/agents/{agent_id}` | 解绑 Agent |

绑定请求：

```json
{
    "group_id": "123456",
    "user_id": null,
    "mode": "primary"
}
```

`mode` 可选：`primary` / `observer` / `candidate`。

### 3.4 Inter-Agent Link

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/links` | 列出 Link |
| POST | `/links` | 创建 Link |
| DELETE | `/links/{from_agent}/{to_agent}` | 删除 Link |

创建请求：

```json
{
    "from_agent": "mai_default",
    "to_agent": "tech_agent",
    "direction": "oneway",
    "permissions": ["ask", "handoff"],
    "visible_memory_scopes": ["shared", "user_global"],
    "max_context_messages": 12
}
```

### 3.5 模型用量、Provider 与制品

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/usage/models/summary` | 按时间、Provider、模型、Agent、模态汇总用量与估算成本 |
| GET | `/usage/models/events` | 分页查询单次物理请求记录 |
| GET | `/usage/models/timeseries` | 按小时/日返回趋势 |
| GET | `/providers` | Provider 健康状态与模型能力摘要，不返回密钥 |
| GET | `/providers/models` | 可用模型及能力清单 |
| POST | `/providers/{id}/test` | 对 Provider 做最小健康测试（写审计，不回显凭据） |
| GET | `/artifacts` | 查询当前调用方有权访问的生成制品 |
| GET | `/artifacts/{id}` | 获取制品元数据或短时签名下载地址 |
| DELETE | `/artifacts/{id}` | 提前删除制品 |

查询参数支持 `from`、`to`、`provider`、`model`、`agent_id`、`session_id`、`modality`、`status`、`group_by`。默认不返回原始 Prompt、响应内容、工具参数或 API Key。会话级明细需要 `usage:detail` scope，聚合数据需要 `usage:read` scope。

### 3.6 统一错误格式

```json
{
    "error": {
        "code": "AGENT_NOT_FOUND",
        "message": "Agent 不存在: tech_agent",
        "retriable": false,
        "trace_id": "trace_abc"
    }
}
```

---

## 四、MCP Server 工具规范

ISAC MCP Server 与 Admin API 共用业务方法和权限模型。

| MCP 工具 | 输入 | 输出 | 说明 |
|----------|------|------|------|
| `agent_create` | AgentConfig | AgentResource | 创建 Agent |
| `agent_update_config` | agent_id + patch | AgentResource | 修改配置 |
| `agent_start` | agent_id | status | 启动 |
| `agent_stop` | agent_id | status | 停止 |
| `channel_bind_agent` | platform + agent_id + scope | BindingResource | 绑定 |
| `channel_unbind_agent` | platform + agent_id + scope | status | 解绑 |
| `route_set_default` | platform + agent_id | RoutingRules | 设置默认 Agent |
| `link_create` | InterAgentLink | LinkResource | 创建 Link |
| `link_delete` | from_agent + to_agent | status | 删除 Link |
| `plugin_set_enabled` | agent_id + plugin_id + enabled | PluginPolicy | 插件启停 |
| `message_send` | agent_id + target + content | MessageResult | 自动化发送入口 |

MCP 工具返回必须包含：

```json
{
    "success": true,
    "trace_id": "trace_abc",
    "data": {}
}
```

---

## 五、Webhook 规范

### 5.1 事件类型

| 事件 | 说明 |
|------|------|
| `message.received` | 收到消息 |
| `message.routed` | 消息完成路由 |
| `message.responded` | Agent 已回复 |
| `agent.created` | Agent 创建 |
| `agent.started` | Agent 启动 |
| `agent.stopped` | Agent 停止 |
| `inter_agent.sent` | Agent 间消息发送 |
| `plugin.loaded` | 插件加载 |
| `plugin.failed` | 插件失败 |
| `memory.created` | 记忆创建 |
| `model.usage_recorded` | 模型用量完成记录（Webhook 默认只发聚合摘要） |
| `provider.health_changed` | Provider 健康状态变化 |
| `control.audit` | 控制面操作审计 |

### 5.2 推送格式

```json
{
    "event": "agent.created",
    "timestamp": 1721234567,
    "trace_id": "trace_abc",
    "data": {
        "agent_id": "tech_agent",
        "actor": "api_token:default"
    }
}
```

### 5.3 签名

Webhook 必须支持 HMAC 签名。

Header：

```text
X-ISAC-Timestamp: 1721234567
X-ISAC-Signature: sha256=<hex>
```

签名内容：

```text
timestamp + "." + raw_body
```

---

## 六、认证、权限与审计

### 6.1 Token Scope

```json
{
    "token_id": "default_admin",
    "scopes": [
        "agent:read",
        "agent:write",
        "routing:write",
        "plugin:write",
        "link:write",
        "message:send",
        "usage:read",
        "usage:detail",
        "provider:read",
        "provider:write",
        "artifact:read",
        "artifact:delete"
    ]
}
```

### 6.2 审计事件

所有写操作必须产生 AuditEvent。

```python
@dataclass
class AuditEvent:
    audit_id: str
    trace_id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    request_summary: dict
    result: str                     # success | failed
    error_code: str = ""
    created_at: int = 0
```

### 6.3 幂等

高风险或可重复提交的写操作应支持：

```text
Idempotency-Key: <client-generated-key>
```

适用：

- 创建 Agent；
- 创建 Link；
- 创建 Webhook；
- 自动化触发器。

---

## 七、自动化安全默认值

通过 API/MCP/Webhook 自动创建的 Agent 默认使用受限配置：

```jsonc
{
    "tools_policy": {
        "bash": false,
        "write_file": false,
        "read_file": false,
        "web_search": true
    },
    "plugins_allow": [],
    "mcp_servers": [],
    "memory_namespace": "agent_private",
    "auto_send_message": false
}
```

规则：

1. 自动创建 Agent 不默认绑定任何高风险工具。
2. 自动创建 Agent 不默认启用第三方插件。
3. 自动创建 Agent 不默认获得共享记忆读写权限。
4. 自动发送 IM 消息必须有显式 `message:send` scope。
5. 所有自动化创建和修改都写审计日志。

---

## 八、WebUI v2 管理与观测

WebUI 是 Control Plane 的浏览器客户端，不得绕过 REST API、权限、审计和配置持久化规则。现有 Vanilla JS 四模块面板保留为 v1 最小实现；v2 按领域拆分页面和前端模块，后端业务逻辑仍由 Control API 提供。

### 8.1 信息架构

| 页面 | 核心内容 | 主要操作 |
|------|----------|----------|
| Dashboard | Agent/Channel/Provider 健康、消息与任务、Token/成本、错误与告警趋势 | 时间范围、Agent/Provider 筛选、跳转详情 |
| Agents | 状态、人格、门控、模型能力、工具/插件/MCP、记忆命名空间 | 创建、复制、启停、编辑、导入导出 |
| Channels & Routing | 连接状态、绑定、默认 Agent、触发词、primary/observer/candidate | 测试连接、绑定、路由预演、保存规则 |
| Providers & Models | Provider 健康、模型能力、模态、限制、成本/延迟层级 | 新增/编辑、替换密钥、健康测试、启停 |
| Usage & Cost | Token、缓存、推理 Token、音视频时长、图片/视频数量、估算成本 | 聚合、明细、趋势、导出、预算告警 |
| Extensions | 插件、MCP Server、工具、命令及 Agent × Channel 启用矩阵 | 安装/加载、启停、权限编辑、连通测试 |
| Memory | 命名空间、Episode、人物画像、行话、索引健康和容量 | 查询、查看来源、纠正、删除、重建索引 |
| Sessions & Tasks | 活跃会话、Agent 状态、工具链、`ProgressEvent`、中断与错误 | 查看时间线、中断任务、重试安全操作 |
| Logs & Audit | 结构化日志、告警、审计、Webhook 发送结果 | 检索、关联 trace、导出、确认告警 |
| System | 全局配置、存储、备份、版本、运行环境 | 校验、差异预览、备份、恢复、重启提示 |

### 8.2 配置编辑事务

```text
GET resource + schema + revision
  → 表单编辑（敏感字段只显示“已配置”）
  → POST /config/validate
  → POST /config/diff
  → 用户确认高影响变更
  → PATCH resource (If-Match: revision)
  → 持久化 + reload/restart plan + AuditEvent
```

规则：

1. UI 表单由服务端 JSON Schema 驱动，但复杂资源允许专用编辑器；前端不能复制一套独立校验规则作为唯一真相。
2. 所有写操作显示影响范围和结构化 diff；删除、停机、解绑、清空记忆、替换 Provider、批量权限修改必须二次确认。
3. 使用 `revision` / `ETag` 做乐观并发；版本冲突返回 `409 CONFIG_CONFLICT`，UI 展示服务器版本与本地变更，不静默覆盖。
4. API Key、Bot Token、Webhook Secret 只允许设置/替换/清除，永不从 API 回显；浏览器不得把管理 Token 或 Provider 密钥写入 `localStorage`。
5. 同源 WebUI 使用 `POST /auth/session` 将一次性登录凭据交换为 `HttpOnly + SameSite=Strict` 会话 Cookie；生产 HTTPS 环境必须同时设置 `Secure`，本机 HTTP 开发模式不得误设导致无法登录；所有写请求校验 CSRF Token。纯 API 客户端继续使用 Bearer Token。
6. 修改结果明确区分 `applied`、`reload_required`、`restart_required`，禁止假装热更新成功。
7. 批量操作必须逐项返回结果并产生审计事件；失败项可重试，已成功项不可重复执行。

### 8.3 实时状态

实时数据统一使用 `/events/stream`（SSE）或受控 WebSocket，事件包括：

- `agent.status_changed`
- `channel.status_changed`
- `provider.health_changed`
- `task.progress`
- `model.usage_recorded`（默认聚合刷新，不逐 Token 推送）
- `alert.triggered`
- `audit.created`

客户端断线后使用 `Last-Event-ID` 恢复；高频指标采用 5–15 秒聚合快照，日志按需订阅并设置速率和行数上限。实时通道只发送当前 Token scope 可读的资源。

### 8.4 SubAgent 任务与日志

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agents/{agent_id}/subagent-runs` | 创建隔离子任务 |
| GET | `/agents/{agent_id}/subagent-runs` | 按会话、状态、时间分页列出任务 |
| GET | `/subagent-runs/{task_id}` | 查询状态、预算、结果和错误摘要 |
| GET | `/subagent-runs/{task_id}/events` | 分页读取脱敏工作日志与证据引用 |
| POST | `/subagent-runs/{task_id}/cancel` | 请求取消运行中任务 |
| GET | `/subagent-runs/{task_id}/artifacts` | 查询当前调用方有权访问的制品 |

权限 scope：`subagent:run`、`subagent:read`、`subagent:cancel`、`subagent:log:read`。父 Agent 只能访问自己创建的任务，管理员按 scope 访问；用户级查询还要满足会话/身份 ACL。

接口不得返回模型原始 reasoning、密钥、Cookie、Authorization Header、完整文件内容或未清洗工具结果。日志默认返回事件摘要和 `evidence_ref`；读取证据需要对应 Artifact/Memory 权限并写审计。取消是幂等请求，任务进入终态后返回原终态，不能伪造成功取消。

WebUI 的 Sessions & Tasks 页面应展示父 Agent、task_id、状态、阶段、耗时、预算、Token、工具次数、错误、证据和时间线，并支持取消；默认折叠参数与结果摘要，敏感字段永不渲染。

### 8.5 前端工程与体验约束

- 采用路由化 SPA 与可复用设计系统；服务端状态集中缓存，筛选/分页写入 URL，避免单个 `app.js` 持续膨胀。
- 桌面端优先但支持 320/768/1024/1440px；复杂表格在小屏切换为摘要列表，不强制横向挤压。
- 所有页面具备 loading、empty、error、stale 和 permission-denied 状态；长任务显示 ProgressEvent 时间线。
- 满足 WCAG 2.1 AA：语义结构、键盘导航、焦点管理、对比度、非颜色状态提示和 reduced-motion。
- 图表必须同时提供表格/文本摘要；成本与 Token 明确单位、时区、价格版本和“估算”标识。
- 前端测试包括组件、API contract、权限矩阵、配置冲突和浏览器端黄金路径；不能只检查静态文件包含字符串。

---

## 九、验收标准

| 能力 | 验收 |
|------|------|
| REST Agent CRUD | 可创建、读取、修改、启动、停止、销毁 Agent |
| Routing API | 可读写默认 Agent、绑定和 observer 规则 |
| MCP Server | 任意 MCP 客户端可完成创建 Agent → 绑定 Channel → 设置默认 Agent |
| Webhook | 支持订阅、签名、重试和事件推送 |
| Auth | 未携带 token 的写操作被拒绝 |
| Scope | token scope 不足时返回 403 |
| Audit | 所有写操作生成 AuditEvent |
| 安全默认值 | 自动化创建 Agent 默认禁用高风险能力 |
| WebUI IA | 十个管理/观测领域均有独立入口，权限不足显示明确状态 |
| Config UX | Schema 校验、diff、确认、ETag 冲突、审计和 reload/restart 结果完整 |
| Web Auth | 管理 Token 不持久化到 localStorage；生产使用 HttpOnly/Secure/SameSite Cookie + CSRF |
| Realtime | SSE/WebSocket 可断线恢复、限流，并按 scope 过滤资源 |
| Accessibility | 键盘、焦点、语义、对比度和图表文本替代满足 WCAG 2.1 AA |
| Usage | 可按 Provider/模型/Agent/模态查询实际用量；重试和回退不漏记 |
| Cost | 价格快照可追溯；未知价格不伪造成本 |
| Privacy | 用量接口和事件不泄露 Prompt、响应、工具参数与凭据 |
| Model Catalog | 可列出模型模态、operation、限制和健康状态，Agent 只能看到授权能力 |
| Model Router | 根据能力、授权、健康、成本与延迟选择模型并给出可观测选择原因 |
| Artifact | 生成媒体有权限、大小、保留期和短时下载控制；Channel 不支持时安全降级 |
| SubAgent | 可创建、查询、取消隔离子任务；主 Agent 可按 task_id 读取脱敏日志与证据且无需重跑 |
| SubAgent Privacy | 日志不含 reasoning、凭据、完整敏感输入或未清洗工具结果；查询受父 Agent/会话/scope ACL 约束 |

---

## 十、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-07-24 | Architect | 新增 SubAgent 任务创建、状态、日志、证据与取消 API，补充 scope、隐私和 WebUI 时间线要求 |
| 2026-07-23 | Architect | 新增 WebUI v2 信息架构、配置编辑事务、实时事件、权限、安全、响应式与无障碍约束 |
| 2026-07-23 | Architect | 新增模型用量资源、查询 API、权限与隐私边界，支持按 Provider/模型/Agent/模态聚合 Token、非 Token 单位与估算成本 |
| 2026-07-22 | Architect | 新增控制面专项规范，补充资源模型、REST/MCP/Webhook schema、认证、审计与自动化安全默认值 |
