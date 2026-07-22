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
- [八、验收标准](#八验收标准)

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

### 3.5 统一错误格式

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
        "message:send"
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

## 八、验收标准

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

---

## 九、文档更新记录

| 日期 | 更新人 | 内容 |
|------|--------|------|
| 2026-07-22 | Architect | 新增控制面专项规范，补充资源模型、REST/MCP/Webhook schema、认证、审计与自动化安全默认值 |
