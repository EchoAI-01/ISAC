# ISAC 使用文档

ISAC (Intelligent Social AI Companion) 是一个多 Agent AI 社交陪伴 Bot 框架,
支持 QQ / Telegram / Discord / WebChat 等多平台接入,
提供记忆、人格、门控、工具、插件、控制面等完整能力。

本指南覆盖快速启动、配置、运行、维护等场景。

---

## 目录

1. [快速开始](#1-快速开始)
2. [配置文件详解](#2-配置文件详解)
3. [运行 ISAC](#3-运行-isac)
4. [Agent 配置](#4-agent-配置)
5. [路由规则](#5-路由规则)
6. [互联 Link](#6-互联-link)
7. [维护与排错](#7-维护与排错)

---

## 1. 快速开始

### 1.1 环境要求

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器 (推荐)
- 可选: Docker (容器化部署见 [Docker 部署](./deployment.md))

### 1.2 安装依赖

```bash
# 克隆仓库
git clone https://github.com/EchoAI-01/ISAC.git
cd ISAC

# 用 uv 安装依赖 (含 onebot 与 embed 本地模型可选 extras)
uv sync --all-extras --dev
```

### 1.3 首次配置

复制默认配置并修改:

```bash
mkdir -p data
cat > data/config.jsonc <<'EOF'
{
    "debug": false,
    "bot_id": "10001",  // QQ 号或平台 bot ID

    "llm": {
        "provider": "openai_compat",
        "api_key": "your-api-key",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1"
    },

    "memory": {
        "enabled": true,
        "embedding": {
            "provider": "fastembed",
            "model": "BGE-small-zh",
            "dimension": 512
        }
    },

    "channels": {
        "onebot": {
            "enabled": true,
            "host": "127.0.0.1",
            "port": 8080,
            "retry_interval": 5,
            "max_retries": 10
        }
    },

    "router": {
        "rules_file": "data/routing.jsonc"
    },

    "control": {
        "enabled": false,
        "host": "127.0.0.1",
        "port": 8765,
        "api_token": "change-me-in-prod"
    }
}
EOF
```

### 1.4 启动

```bash
# 直接运行
uv run python -m isac

# 或 Docker
docker compose up -d
```

---

## 2. 配置文件详解

### 2.1 `data/config.jsonc` 全局配置

| 字段 | 类型 | 说明 |
|------|------|------|
| `debug` | bool | 调试日志开关 |
| `bot_id` | string | Bot 自身 ID (用于 has_at 判定) |
| `llm` | object | LLM Provider 配置 |
| `memory` | object | 记忆系统配置 |
| `persona` | object | 全局人格配置 (各 Agent 可覆盖) |
| `channels` | object | 各平台适配器配置 |
| `router` | object | 路由规则文件路径 |
| `control` | object | 控制面 (Admin API + WebUI + MCP) 配置 |
| `policy` | object | 全局策略 (plugins_deny / tools_policy) |

### 2.2 LLM 配置

```jsonc
"llm": {
    "provider": "openai_compat",  // 支持 OpenAI / DeepSeek / Moonshot 等兼容 API
    "api_key": "sk-xxx",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com/v1",
    "temperature": 0.7,
    "max_tokens": 2048
}
```

未配置 `provider` 或 `api_key` 时, ISAC 使用 `StubProvider` 保证可启动 (仅返回 stub 响应, 用于测试)。

### 2.3 记忆系统

```jsonc
"memory": {
    "enabled": true,
    "embedding": {
        "provider": "fastembed",  // 或 "openai_compat"
        "model": "BGE-small-zh",
        "dimension": 512
    },
    "reranker": {
        "provider": "bge-reranker"  // 或 "cohere" / "jina"
    }
}
```

`memory.enabled=false` 时使用 `NoOpMemoryPipeline` (检索返回空, 存储空操作), 主链路不受影响。

---

## 3. 运行 ISAC

### 3.1 直接运行

```bash
# 前台运行 (Ctrl+C 退出)
uv run python -m isac

# 后台运行 + 日志
nohup uv run python -m isac > isac.log 2>&1 &
```

### 3.2 Docker 运行

```bash
# 构建并启动
./scripts/docker_deploy.sh build
./scripts/docker_deploy.sh up

# 查看日志
./scripts/docker_deploy.sh logs

# 健康检查
./scripts/docker_deploy.sh health

# 停止
./scripts/docker_deploy.sh down
```

### 3.3 平台适配器

| 平台 | 启用方式 | 配置示例 |
|------|---------|---------|
| QQ (OneBot) | `channels.onebot.enabled=true` + NapCat 反向 WebSocket | 见 [1.3](#13-首次配置) |
| Telegram | `channels.telegram.enabled=true` + `bot_token` | [Telegram 配置](../isac/channel/adapters/telegram/adapter.py) |
| Discord | `channels.discord.enabled=true` + `bot_token` | [Discord 配置](../isac/channel/adapters/discord/adapter.py) |
| WebChat | `channels.webchat.enabled=true` + bind host/port | [WebChat 配置](../isac/channel/adapters/webchat/adapter.py) |

---

## 4. Agent 配置

每个 Agent 独立配置在 `data/agents/<agent_id>/config.jsonc`:

```jsonc
{
    "agent_id": "tech_assistant",
    "display_name": "技术助手",
    "enabled": true,
    "persona": {
        "attention_drift": { "level": "active" },
        "expression_style": { "formality": 0.7, "verbosity": 0.6 }
    },
    "memory_namespace": "tech",  // 默认 = agent_id; "shared" 表示跨 Agent 共享
    "trigger_words": ["技术", "代码", "bug"],
    "tools_policy": {
        "bash": "deny",        // 显式禁用 bash
        "web_search": "allow"
    },
    "commands_allow": ["focus", "mute", "unmute"],
    "plugins_allow": ["*"],
    "plugins_deny": [],
    "mcp_servers": ["filesystem", "github"]  // 允许使用的 MCP Server
}
```

通过 Admin API 创建 (会自动持久化):

```bash
curl -X POST http://127.0.0.1:8765/api/v1/agents \
    -H "Authorization: Bearer $ISAC_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"agent_id": "tech_assistant", "display_name": "技术助手"}'
```

---

## 5. 路由规则

`data/routing.jsonc` 定义消息路由:

```jsonc
{
    "bindings": [
        {
            "platform": "qq",
            "agent_id": "tech_assistant",
            "group_id": "123456789",  // 指定群, 与 user_id 都为 None 表示整个平台
            "user_id": null
        }
    ],
    "default_agents": {
        "qq": "default",  // 平台默认 Agent
        "telegram": "default"
    }
}
```

路由优先级: 显式绑定 > 触发词 > 默认 Agent > DROP。

热更新: 修改 `routing.jsonc` 后通过 Admin API PUT `/api/v1/routing/rules` 触发热加载。

---

## 6. 互联 Link

Agent 间通信 (InterAgentBus) 必须显式配置 Link (ACL 默认拒绝):

```bash
# 创建双向 Link
curl -X POST http://127.0.0.1:8765/api/v1/links \
    -H "Authorization: Bearer $ISAC_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"from_agent": "tech_assistant", "to_agent": "research_agent", "direction": "both"}'
```

`direction: "both"` 双向; `"oneway"` 仅 from → to。

持久化到 `data/links.jsonc`。

---

## 7. 维护与排错

### 7.1 健康检查

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok"}
```

### 7.2 审计日志查询

```bash
# 最近 20 条 create_agent 动作
curl "http://127.0.0.1:8765/api/v1/audit?action=create_agent&limit=20" \
    -H "Authorization: Bearer $ISAC_API_TOKEN"
```

### 7.3 常见问题

| 问题 | 排查 |
|------|------|
| 启动报 `ModuleNotFoundError: aiocqhttp` | `uv sync --extra onebot` 装可选依赖 |
| OneBot 不连接 | 检查 NapCat 反向 WebSocket 配置 host:port 是否匹配 |
| LLM 调用失败 | 检查 `llm.api_key` 与 `base_url`; 看日志是否 RateLimitError |
| Agent 不回复 | 检查 `gating.evaluate` 是否触发 (reply_necessity 阈值); 看 TurnScheduler 频率 |
| 记忆检索空 | 检查 `memory.enabled=true`; EmbeddingManager 是否降级 (is_degraded=true) |
| 控制面 401 | 确认 Authorization 头 `Bearer <token>` 与 `control.api_token` 一致 |

### 7.4 日志位置

- 应用日志: stdout (structlog 格式)
- 审计日志: `data/audit.ndjson` (一行一条 JSON, 可用 `jq` 分析)
- 控制面访问日志: uvicorn 默认 stdout (warning 级别)

---

## 相关文档

- [架构总览](./ARCHITECTURE.md)
- [开发规范](./DEVELOP.md)
- [规范契约](./SPECIFICATION.md)
- [开发计划 SOW](./DEVELOPMENT_PLAN.md)
- [Docker 部署](./deployment.md)
- [API 文档](./api.md)
- [插件开发指南](./plugin_development.md)
- [控制面自动化指南](./control_automation.md)
