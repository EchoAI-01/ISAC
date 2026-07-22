# ISAC 控制面自动化指南

ISAC 控制面提供三种自动化入口, 适合不同的集成场景:

1. **Admin REST API** - 最通用, 适合程序化集成 (CI/CD, 脚本, 内部系统)
2. **MCP Server** - 适合 LLM Agent 自主管理 ISAC (Claude / GPT 等)
3. **Webhooks** - 适合事件驱动场景 (消息到达时触发外部系统)

---

## 1. Admin REST API 自动化

### 1.1 典型场景

- CI/CD: 部署时自动创建 Agent + 配置 Link
- 监控: 定时查询审计日志, 异常告警
- 运维: 批量启动/停止 Agent

### 1.2 示例: CI/CD 集成

```bash
#!/bin/bash
# 部署脚本: 启动 tech_agent + 配置路由

API=http://127.0.0.1:8765/api/v1
TOKEN=$ISAC_API_TOKEN

# 1. 创建 Agent
curl -X POST $API/agents \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "agent_id": "tech_agent",
        "display_name": "技术助手",
        "trigger_words": ["技术", "代码"]
    }'

# 2. 启动 Agent
curl -X POST $API/agents/tech_agent/start \
    -H "Authorization: Bearer $TOKEN"

# 3. 设置默认路由
curl -X PUT $API/routing/rules \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "bindings": [],
        "default_agents": {"qq": "tech_agent"}
    }'

# 4. 创建互联 Link
curl -X POST $API/links \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent": "tech_agent", "to_agent": "research_agent", "direction": "both"}'

echo "✓ 部署完成"
```

### 1.3 Python SDK 示例

```python
import httpx

class ISACClient:
    def __init__(self, base_url: str, api_token: str):
        self.base = base_url.rstrip("/") + "/api/v1"
        self.headers = {"Authorization": f"Bearer {api_token}"}

    async def create_agent(self, agent_id: str, display_name: str = ""):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base}/agents",
                headers=self.headers,
                json={"agent_id": agent_id, "display_name": display_name},
            )
            return response.json()

    async def start_agent(self, agent_id: str):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base}/agents/{agent_id}/start",
                headers=self.headers,
            )
            return response.json()

    async def query_audit(self, action: str | None = None, limit: int = 100):
        async with httpx.AsyncClient() as client:
            params = {"limit": limit}
            if action:
                params["action"] = action
            response = await client.get(
                f"{self.base}/audit",
                headers=self.headers,
                params=params,
            )
            return response.json()
```

---

## 2. MCP Server 集成

### 2.1 典型场景

- LLM Agent 自主管理 ISAC (如 Claude 通过 MCP 创建 Agent 后调用)
- IDE 插件 (如 Cursor / VS Code MCP 客户端)
- 自动化工作流编排 (n8n / Zapier 等通过 MCP 协议)

### 2.2 MCP 工具清单

ISAC MCP Server 暴露 11 个工具:

| 工具 | 说明 |
|------|------|
| `agent_create` | 创建 Agent |
| `agent_update_config` | 修改 Agent 参数 |
| `agent_start` | 启动 Agent |
| `agent_stop` | 停止 Agent |
| `channel_bind_agent` | 绑定 Channel ↔ Agent |
| `channel_unbind_agent` | 解绑 Channel ↔ Agent |
| `route_set_default` | 设置平台默认 Agent |
| `link_create` | 创建互联 Link |
| `link_delete` | 删除互联 Link |
| `plugin_set_enabled` | 插件启用矩阵 |
| `message_send` | 以某 Agent 身份发送消息 (自动化流程入口) |

### 2.3 启动 MCP Server

MCP Server 集成在控制面启动流程中。配置 `control.mcp.enabled=true` 后,
MCP 客户端可通过 stdio 协议连接。

### 2.4 Claude Desktop 集成示例

`~/.config/claude/claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "isac": {
            "command": "python",
            "args": ["-m", "isac.control.mcp_server"],
            "env": {
                "ISAC_API_TOKEN": "your-token",
                "ISAC_MCP_TRANSPORT": "stdio"
            }
        }
    }
}
```

### 2.5 JSON-RPC 示例

```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
{"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "meta": {"authorization": "Bearer your-token"},
        "name": "agent_create",
        "arguments": {"agent_id": "auto_agent", "display_name": "Auto Agent"}
    }
}
```

---

## 3. Webhooks 自动化

### 3.1 典型场景

- 消息到达 → 推送到 Slack 频道
- Agent 创建 → 触发配置同步
- 审计日志异常 → 触发 PagerDuty 告警

### 3.2 订阅与推送

```python
import httpx

async def setup_webhooks():
    async with httpx.AsyncClient() as client:
        # 订阅 message.received 事件
        response = await client.post(
            "http://127.0.0.1:8765/api/v1/webhooks/subscribe",
            json={"event": "message.received", "url": "https://my-app.com/hook"},
        )
        return response.json()
```

Webhook 推送 payload 格式:

```json
{
    "event": "message.received",
    "data": {
        "msg_id": "...",
        "platform": "qq",
        "user_id": "...",
        "content": "..."
    }
}
```

### 3.3 自动化触发 (/automation/trigger)

外部系统可主动触发任意事件:

```bash
curl -X POST http://127.0.0.1:8765/api/v1/automation/trigger \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "event": "custom.alert",
        "data": {"level": "critical", "msg": "外部告警"}
    }'
```

所有订阅 `custom.alert` 的 Webhook URL 都会收到推送。

### 3.4 重试机制

- 失败自动重试 3 次 (指数退避 1s/2s/4s)
- 重试耗尽后记录日志, 不影响主流程
- HTTP 状态码 2xx 视为成功, 其他视为失败

---

## 4. 安全建议

### 4.1 通用

- 用强随机 token (`openssl rand -hex 32`)
- 控制面仅监听 127.0.0.1 (生产前置 nginx)
- 定期审计 `audit.ndjson`, 关注异常动作

### 4.2 MCP 特殊

- MCP `tools/call` 受 Bearer Token 认证
- protocol-level 方法 (initialize / tools/list) 不需认证
- MCP 客户端进程权限应最小化

### 4.3 Webhooks 特殊

- 订阅 URL 应使用 HTTPS
- 推送失败 3 次后停止重试, 避免雪崩
- 订阅 URL 失效应及时 unsubscribe

---

## 5. 综合自动化场景

### 5.1 多 Agent 协同

```
用户消息 → QQ (OneBot)
    ↓
MessageRouter → tech_agent
    ↓
tech_agent: ask_agent 工具 → InterAgentBus → research_agent
    ↓
research_agent 处理 → 返回结果
    ↓
tech_agent 整合 → 回复用户
```

### 5.2 CI/CD 完整流程

```bash
# 部署阶段
./scripts/docker_deploy.sh up
sleep 5

# 等 ISAC 启动
for i in {1..30}; do
    curl -sf http://127.0.0.1:8765/health && break
    sleep 1
done

# 自动化配置
./scripts/setup_isac.sh  # 创建 Agent + Link + 路由

# 触发 smoke test
curl -X POST http://127.0.0.1:8765/api/v1/automation/trigger \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"event": "deploy.completed", "data": {"version": "1.0"}}'

echo "✓ ISAC 部署完成"
```

---

## 相关文档

- [API 文档](./api.md)
- [Docker 部署](./deployment.md)
- [使用文档](./usage.md)
- [插件开发指南](./plugin_development.md)
