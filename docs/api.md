# ISAC Admin API 文档

ISAC Admin API 提供对 Agent / 路由 / Link / 插件矩阵 / 审计日志的管理接口。
所有 `/api/v1` 端点 (包括 GET 读操作) 都需要认证: `Authorization: Bearer <token>`
或登录后的会话 Cookie; 仅 `/health` 与默认 `/metrics` (Prometheus 文本) 免认证。

**Base URL**: `http://127.0.0.1:8765/api/v1`

**OpenAPI docs**: `http://127.0.0.1:8765/docs` (Swagger UI, 默认关闭; 见下方契约基线)

---

## API 契约基线 (FE0)

本 API 的契约基线以 `docs/api/openapi.json` 为准 (由 `scripts/export_openapi.py`
从 `create_control_app` 实时导出)。前后端分离后, 前端围绕此基线开发。

**契约冻结规则**:
- 版本前缀 `/api/v1` 保持; 破坏性变更 (删端点 / 改参数语义 / 改错误码) 须升
  版本前缀 (如 `/api/v2`) 并保留 v1 过渡期。
- 运行时 `/openapi.json` 按 R15 安全默认关闭 (`control.docs_enabled=false`),
  防误暴露完整端点列表; 契约以归档文件为准而非运行时端点。
- 任何 API 变更 (新增/修改/删除端点、改错误码) 须先改 `CONTROL_PLANE_SPEC.md`
  对应章节 + 更新本文档端点说明, 再跑 `scripts/export_openapi.py` 刷新
  `docs/api/openapi.json` 基线, 否则前后端契约漂移。

**统一错误格式** (详见 `CONTROL_PLANE_SPEC.md` §3.6): `{"detail": {"code", "message"}}`,
未捕获异常返回 500 `{"detail": {"code": "INTERNAL_ERROR", "message": "Internal server error"}}`。

---

## 认证

所有 `/api/v1` 端点 (包括 GET 读操作) 都必须在请求头携带以下凭证之一:

```
Authorization: Bearer <api_token>
```

或使用同源 WebUI 的会话 Cookie:

- `POST /api/v1/auth/session`, body `{"token": "<api_token>"}` → 签发 HttpOnly 会话 Cookie + CSRF Cookie, 返回 `{"status": "ok"}`;
- 之后写请求 (POST/PUT/PATCH/DELETE) 必须带与 `csrf_token` Cookie 匹配的 `X-CSRF-Token` 请求头 (双提交校验), 否则 403 `CSRF_REQUIRED`;
- `DELETE /api/v1/auth/session` 登出并清除两个 Cookie。

`api_token` 在 `data/config.jsonc` 的 `control.api_token` 字段配置; 需要按权限细分时改用
`control.tokens[]` (每个 token 带 scope, 缺 scope 返回 403 `SCOPE_FORBIDDEN`)。
仅 `/health` 与默认 `/metrics` 免认证 (`control.metrics_auth_enabled=true` 时 `/metrics` 也需 Bearer)。

### 首登 setup 状态机 (T3-backend)

控制面内置默认 `control.enabled=true` + `control.setup_enabled=true`:

- 未配任何静态凭证 (`api_token` / `tokens[]`) 且未设置管理密码时, 全部 admin 端点返回
  **428 `SETUP_REQUIRED`**, 仅 `/health` 与 `/setup` 可用;
- `POST /api/v1/setup` (body `{"password": "<新密码>"}`) 设置管理密码后认证生效;
  重复调用返回 409 `SETUP_ALREADY_DONE` (轮换走 CLI 重置);
- 配置了 `api_token` 或 `tokens[]` 即视为静态凭证: **跳过 setup**, 直接用 token 认证;
  此时 `POST /setup` 返回 403 `SETUP_NOT_ALLOWED`;
- `GET /api/v1/setup` 返回 `{"setup_required": bool}` 供前端首登向导判断;
- 会话 Cookie 机制未启用 (无 session secret) 时 `POST /auth/session` 返回 404 `SESSION_AUTH_DISABLED`。

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
        "trigger_words": ["技术", "代码"]
    }'
```

响应:
```json
{"agent_id": "tech_agent", "status": "stopped"}
```

**注意**: 创建路径 (Admin API / MCP `agent_create` / Webhook 触发) 强制套用受限默认模板,
请求里的能力字段 (`tools_policy` / `plugins_allow` / `plugins_deny` / `commands_allow` /
`mcp_servers`) 会被直接丢弃; 需要放宽时创建后用
`PATCH /api/v1/agents/{agent_id}` 显式授予并持久化。

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

`keep_memory=false` 清理该 Agent 命名空间下的记忆数据 (episodes / person_profiles /
jargon + `data/memory/vectors-<ns>.db` 向量库文件 + graph 边); 若该 Agent 使用
`memory_namespace=shared` 共享命名空间 (多 Agent 共用), 则**拒绝清理**, 仅销毁 Agent。

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
```

响应 (聚合各子系统状态; `status` 为 `ok` | `degraded`, 后者表示无可用
Agent 且无 Channel):

```json
{
    "status": "ok",
    "subsystems": {
        "agents": {"total": 2, "running": 1},
        "llm": "configured",
        "channels": ["webchat"],
        "control": {"enabled": true, "host": "127.0.0.1", "port": 8765}
    },
    "setup_required": false
}
```

`llm` 取值 `configured` | `stub` (未配真实 key) | `not_configured` | `unknown`;
`setup_required=true` 时控制面处于首登待设置态 (仅 `/setup` 与 `/health` 可用)。

---

## 端点覆盖总览

除上文详述的 Agent / 路由 / Link / 插件矩阵 / 审计端点外, 控制面 (以
`docs/api/openapi.json` 为契约基线) 还包含以下主要端点组:

| 端点组 | 说明 |
|--------|------|
| `GET/POST /api/v1/setup`, `POST/DELETE /api/v1/auth/session` | 首登设密码 + 会话 Cookie 登录/登出 (见"认证"节) |
| `PATCH /api/v1/agents/{agent_id}` | 部分更新 AgentConfig; 支持 `If-Match: <revision>` 乐观锁 (Header 优先, 兼容 `?if_match=`), revision 不符返回 409 `CONFIG_CONFLICT` |
| `GET /api/v1/agents/{agent_id}/config` | 读取全量 AgentConfig + 真实 revision (供编辑页乐观锁) |
| `GET /api/v1/plugins/loaded`、`GET /api/v1/plugins/marketplace`、`GET /api/v1/plugins/failed` | 已加载 / 市场清单 / 加载失败清单 |
| `POST /api/v1/plugins/install`、`POST /api/v1/plugins/{name}/reload`、`DELETE /api/v1/plugins/{name}`、`POST /api/v1/plugins/{name}/retry` | 插件市场四操作: 安装 / 热重载 / 卸载 / 重试 (需 `control.plugins.allow_install=true`) |
| `GET/PATCH /api/v1/config/global`、`POST /api/v1/config/global/reload`、`POST /api/v1/config/validate`、`POST /api/v1/config/diff` | 全局配置读取 / 差量更新 / 热重载 / 校验与变更预览 |
| `GET /api/v1/events/stream` | SSE 实时事件流 (Last-Event-ID 断线恢复; 浏览器 EventSource 用会话 Cookie) |
| `GET /api/v1/logs/tail` | SSE 实时日志 (基线认证; `tokens[]` scope 模型下需 `"*"` 通配 scope) |
| `GET /api/v1/sessions`、`/sessions/{id}`、`/sessions/{id}/messages` | 会话与消息查询 |
| `GET /api/v1/memory/{agent_id}/items` (及 episodes / profiles / jargon) + 治理写操作 (freeze/protect/restore/delete) | 记忆检索与治理 |
| `GET /api/v1/providers`、`GET /api/v1/providers/models`、`POST /api/v1/providers/{provider_id}/test` | Provider 清单 / 模型目录 / 连通性测试 |
| `GET/POST /api/v1/agents/{agent_id}/subagent-runs`、`GET /api/v1/subagent-runs[...]`、`POST /api/v1/subagent-runs/{task_id}/cancel` | SubAgent 运行查询 / 事件 / 取消 |
| `GET /api/v1/workflows[...]`、`POST /api/v1/workflows/{workflow_id}/start` | 工作流查询与启动 |
| `POST /api/v1/identity/bind`、`GET /api/v1/identity/conflicts` | 跨平台身份绑定与冲突查询 |
| `GET/POST /api/v1/tenants[...]` (含成员管理) | 多租户管理 |
| `GET /api/v1/approvals[...]`、`POST /api/v1/approvals/{approval_id}/decide` | 审批门查询与决策 |
| `GET /api/v1/usage/summary` (及 `/usage/events` / `/usage/timeseries`) | 用量与成本 |
| `GET/POST/DELETE /api/v1/webhooks`、`POST /api/v1/automation/trigger` | Webhook 订阅 / 取消 / 外部触发 |
| `GET /api/v1/audit` (已详述) | 审计日志; `tokens[]` scope 模型下需 `"*"` |

> **条件挂载**: 标注为注入式挂载的端点组仅对应子系统启用时存在 —— `usage_store`
> 需 `observability.usage.enabled=true`、memory 组需 `memory.enabled=true`、
> tenancy 需租户管理开启、subagent 需 `subagent.enabled=true`、providers 需
> ProviderManager + 模型目录、events/logs 需事件总线/日志缓冲启用。
> 前端应以 `docs/api/openapi.json` 静态基线为准, 运行时可用端点以实际进程为准。

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
| 400 | INVALID_IF_MATCH | If-Match 不是整数 revision |
| 401 | UNAUTHORIZED | Bearer Token 缺失或错误 |
| 403 | SCOPE_FORBIDDEN | Token scope 不含端点所需 scope (配置 `control.tokens[]` 时) |
| 403 | CSRF_REQUIRED | 会话 Cookie 认证的写请求缺少/不匹配 `X-CSRF-Token` |
| 403 | SETUP_NOT_ALLOWED | 已配置静态凭证 (api_token/tokens), setup 通道关闭 |
| 404 | AGENT_NOT_FOUND | agent_id 不存在 |
| 409 | AGENT_EXISTS | agent_id 已存在 |
| 409 | CONFIG_CONFLICT | If-Match revision 与当前 revision 不一致 |
| 409 | SETUP_ALREADY_DONE | 管理密码已设置, 重复调用 POST /setup |
| 428 | SETUP_REQUIRED | 首登未设置密码且无静态凭证, 需先 POST /api/v1/setup |
