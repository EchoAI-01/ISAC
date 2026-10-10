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

MCP Server 集成在控制面启动流程中 (随 ISAC 服务一起启动): 配置
`control.mcp_server.enabled=true` 后, 进程会 spawn 一个 stdio JSON-RPC 桥接,
通过 stdin/stdout NDJSON 收发 (与主进程同生命周期), 默认关闭。

> 注意: 当前实现**没有独立入口** (无 `python -m isac.control.mcp_server` 形式、
> 无 console script), 也没有 `ISAC_MCP_TRANSPORT` 环境变量; stdio 面向"随服务启动、
> 由同机父进程持有管道"的场景。外部 MCP 客户端 (如 Claude Desktop) 直接拉起 ISAC
> 作为 MCP Server **暂未支持** —— 外部自动化请走 Admin REST API, 或等待后续节点。

### 2.4 JSON-RPC 示例

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
        # 订阅 message.responded 事件 (POST /api/v1/webhooks; 需 Bearer + webhook:write scope)
        response = await client.post(
            "http://127.0.0.1:8765/api/v1/webhooks",
            headers={"Authorization": "Bearer <token>"},
            json={"event": "message.responded", "url": "https://my-app.com/hook"},
        )
        return response.json()

# 查询订阅: GET    http://127.0.0.1:8765/api/v1/webhooks[?event=...]
# 取消订阅: DELETE http://127.0.0.1:8765/api/v1/webhooks?event=message.responded&url=https://my-app.com/hook
```

Webhook 推送 payload 格式:

```json
{
    "event": "message.responded",
    "data": {
        "msg_id": "...",
        "platform": "qq",
        "user_id": "...",
        "content": "..."
    }
}
```

> **当前实际派发的事件**: `message.responded` (Agent 处理完成)、`message.sent`
> (回复发送完成)、内置告警 `alert.*` (见 `observability/alerting.py` 默认规则),
> 以及 `POST /automation/trigger` 触发的自定义事件。
> 事件目录中的 `message.received` / `agent.created` / `agent.stopped` /
> `inter_agent.sent` 暂未在生产代码中派发, 订阅了也不会收到推送。

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

- 最多 3 次尝试 (首次 + 2 次重试), 退避 1s / 2s
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
- 单次推送最多 3 次尝试 (首次 + 2 重试), 之后放弃, 避免雪崩
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

# 自动化配置 (创建 Agent + 启动 + 默认路由; 完整示例见 scripts/smoke_control_setup.py)
curl -X POST http://127.0.0.1:8765/api/v1/agents \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"agent_id": "tech_agent", "display_name": "技术助手"}'
curl -X POST http://127.0.0.1:8765/api/v1/agents/tech_agent/start \
    -H "Authorization: Bearer $TOKEN"
curl -X PUT http://127.0.0.1:8765/api/v1/routing/rules \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"bindings": [], "default_agents": {"qq": "tech_agent"}}'

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
