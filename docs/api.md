# ISAC Admin API 文档

ISAC Admin API 提供对 Agent / 路由 / Link / 插件矩阵 / 审计日志的管理接口。
所有写操作需 Bearer Token 认证; 读操作与 protocol-level MCP 方法不需认证。

**Base URL**: `http://127.0.0.1:8765/api/v1`

**OpenAPI docs**: `http://127.0.0.1:8765/docs` (Swagger UI)

---

## 认证

所有写操作 (POST/PUT/DELETE) 必须在请求头携带:

```
Authorization: Bearer <api_token>
```

`api_token` 在 `data/config.jsonc` 的 `control.api_token` 字段配置。
未配置时跳过认证 (仅开发模式, 不推荐生产)。

---

## Agent 管理端点

### POST /agents - 创建 Agent

```bash
curl -X POST http://127.0.0.1:8765/api/v1/agents \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "agent_id": "tech_agent",
        "display_name": "技术助手",
        "trigger_words": ["技术", "代码"],
        "tools_policy": {"bash": "deny"},
        "commands_allow": ["focus", "mute", "unmute"]
    }'
```

响应:
```json
{"agent_id": "tech_agent", "status": "stopped"}
```

配置会自动持久化到 `data/agents/tech_agent/config.jsonc`。

### GET /agents - 列出所有 Agent

```bash
curl http://127.0.0.1:8765/api/v1/agents -H "Authorization: Bearer $TOKEN"
```

响应:
```json
[
    {"agent_id": "tech_agent", "status": "running"},
    {"agent_id": "default", "status": "running"}
]
```

### GET /agents/{agent_id} - 查询单个 Agent

```bash
curl http://127.0.0.1:8765/api/v1/agents/tech_agent -H "Authorization: Bearer $TOKEN"
```

### POST /agents/{agent_id}/start - 启动 Agent

```bash
curl -X POST http://127.0.0.1:8765/api/v1/agents/tech_agent/start \
    -H "Authorization: Bearer $TOKEN"
```

响应: `{"agent_id": "tech_agent", "status": "running"}`

### POST /agents/{agent_id}/stop - 停止 Agent

### DELETE /agents/{agent_id}?keep_memory=true - 销毁 Agent

```bash
curl -X DELETE "http://127.0.0.1:8765/api/v1/agents/tech_agent?keep_memory=true" \
    -H "Authorization: Bearer $TOKEN"
```

`keep_memory=false` 会清理 `data/agents/tech_agent/memory/` 目录。

---

## 路由规则端点

### GET /routing/rules

```bash
curl http://127.0.0.1:8765/api/v1/routing/rules -H "Authorization: Bearer $TOKEN"
```

响应:
```json
{
    "bindings": [
        {"platform": "qq", "agent_id": "tech_agent", "group_id": "12345", "user_id": null}
    ],
    "default_agents": {"qq": "default"}
}
```

### PUT /routing/rules - 更新路由规则

```bash
curl -X PUT http://127.0.0.1:8765/api/v1/routing/rules \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "bindings": [
            {"platform": "qq", "agent_id": "tech_agent", "group_id": null, "user_id": null}
        ],
        "default_agents": {"qq": "tech_agent", "telegram": "default"}
    }'
```

规则会持久化到 `data/routing.jsonc`。

---

## 互联 Link 端点

### GET /links

```bash
curl http://127.0.0.1:8765/api/v1/links -H "Authorization: Bearer $TOKEN"
```

响应:
```json
[
    {"from_agent": "tech_agent", "to_agent": "research_agent", "direction": "both", "enabled": true}
]
```

### POST /links

```bash
curl -X POST http://127.0.0.1:8765/api/v1/links \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent": "tech_agent", "to_agent": "research_agent", "direction": "both"}'
```

Link 持久化到 `data/links.jsonc`。

### DELETE /links?from_agent=X&to_agent=Y

```bash
curl -X DELETE "http://127.0.0.1:8765/api/v1/links?from_agent=tech_agent&to_agent=research_agent" \
    -H "Authorization: Bearer $TOKEN"
```

---

## 插件启用矩阵端点

### GET /agents/{agent_id}/plugins

```bash
curl http://127.0.0.1:8765/api/v1/agents/tech_agent/plugins \
    -H "Authorization: Bearer $TOKEN"
```

响应:
```json
{"plugins_allow": ["*"], "plugins_deny": []}
```

### PUT /agents/{agent_id}/plugins

```bash
curl -X PUT http://127.0.0.1:8765/api/v1/agents/tech_agent/plugins \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"plugins_allow": ["my_plugin"], "plugins_deny": ["evil_plugin"]}'
```

矩阵持久化到 `data/agents/tech_agent/config.jsonc`。

---

## 审计日志端点

### GET /audit - 查询审计日志

```bash
# 最近 20 条
curl "http://127.0.0.1:8765/api/v1/audit?limit=20" \
    -H "Authorization: Bearer $TOKEN"

# 过滤 create_agent 动作
curl "http://127.0.0.1:8765/api/v1/audit?action=create_agent" \
    -H "Authorization: Bearer $TOKEN"

# 按路径前缀过滤
curl "http://127.0.0.1:8765/api/v1/audit?path_prefix=/api/v1/agents" \
    -H "Authorization: Bearer $TOKEN"
```

响应 (最新到最旧):
```json
[
    {
        "timestamp": 1717000000.0,
        "iso": "2024-05-30T12:00:00",
        "actor": "authenticated",
        "method": "POST",
        "path": "/api/v1/agents",
        "action": "create_agent",
        "target": "tech_agent",
        "status_code": 200,
        "detail": ""
    }
]
```

审计日志同时写入 `data/audit.ndjson` (一行一条 JSON)。

---

## 健康检查端点

### GET /health (无需认证)

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok"}
```

---

## 错误响应

所有端点错误统一格式:

```json
{
    "detail": {
        "code": "AGENT_NOT_FOUND",
        "message": "tech_agent"
    }
}
```

常见错误码:

| HTTP | code | 说明 |
|------|------|------|
| 400 | INVALID_CONFIG | AgentConfig 字段错误 |
| 401 | UNAUTHORIZED | Bearer Token 缺失或错误 |
| 404 | AGENT_NOT_FOUND | agent_id 不存在 |
| 409 | AGENT_EXISTS | agent_id 已存在 |
