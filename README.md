# ISAC — Intelligent Social AI Companion

下一代多 Agent AI 社交陪伴 Bot 框架。

把 **LLM 的拟人表达**、**会话级拟人化运行时**、**记忆检索**、**回复门控**、**多 Agent 协作**与 **IM 平台适配**
拆解为可组合的独立子系统，通过 ConversationRuntime 与 System Prompt 组装器协同，让 Bot 行为可按配置定制而无需
改代码。

---

## 一句话定位

> ISAC 不是另一个"接 LLM 回复消息"的 Bot 脚手架。
> 它把「AI 社交陪伴」拆成 **门控决策**（要不要回）、**记忆检索**（该记得什么）、
> **人格注入**（用什么风格回）与 **多 Agent 路由**（哪个 Agent 回）四层流水线，
> 每层都可独立替换或扩展。

---

## 核心概念

```
用户发消息 → Channel Adapter → Gateway(事件总线/会话/并发锁)
                                  │
                            MessageRouter(显式绑定/触发词/默认Agent)
                                  │
                         ┌──── AgentInstance ────┐
                         │  GatingSystem(门控)    │ ← 要不要回？要不要等？
                         │  SystemPromptBuilder   │ ← 组装记忆+人格+工具说明
                         │  ISACAgentLoop(LLM循环) │ ← 带重试/回退/工具调用
                         │  MemoryPipeline(检索)  │ ← 混合检索+重排序
                         │  PersonaManager(人格)  │ ← 注意力漂移/表达风格/情绪
                         └────────────────────────┘
                                  │
                            Channel Adapter.send() → 用户收到回复
```

## 关键设计决策

| 设计 | 说明 |
|------|------|
| **门控先于 Agent** | 调用 LLM 前先由门控系统评定回复必要性；无需回复的消息不消耗 token |
| **Channel 与 Agent 解耦** | 一个 QQ 号可服务多个 Agent，消息由 Router 按绑定/触发词/默认规则分发 |
| **多 Agent 单进程** | 多个 Agent 实例在单进程内运行，共享 Provider 连接池与嵌入模型，降低资源消耗 |
| **Agent 互联显式化** | InterAgentBus + ACL 链路，Agent 默认不互通，需显式授权才能 `ask_agent()` |
| **控制面/数据面分离** | 消息处理链路（数据面）与 Admin API / MCP Server（控制面）解耦；控制面崩溃不影响发消息 |
| **拟人表达靠 Prompt，拟人行为靠 Runtime** | 注意力漂移、表达风格、情绪、记忆等通过 System Prompt 注入；回复节奏、等待、主动、打断等由 ConversationRuntime 管理 |
| **兼容存量插件** | 计划桥接 AstrBot Star 与 MaiBot 插件系统，同时提供 ISAC Native SDK 承载独有能力 |

---

## 项目状态

**Alpha (K1-K8 稳定化阶段)** — 框架骨架 + 真实 LLM Provider + 持久化恢复 + 安全基线 + 多 Agent E2E 已通, 接近可用版本准入。

K1-K7 已完成 (K8 CI/Docker/浏览器测试门禁进行中):

- 应用生命周期 (`ApplicationRuntime` 统一 TaskGroup + SIGINT/SIGTERM 优雅关闭)
- 真实 LLM Provider (`OpenAICompatProvider` httpx 实现, 含 SSE 流式 + Tool Call + 429/5xx 分类)
- Storage Schema init + BM25 启动恢复 + shared namespace ACL
- 原子配置写入 (tmp + fsync + os.replace)
- 单/多 Agent × Channel 端到端集成测试
- 安全基线: Webhook SSRF 防护 / SecretStore AES-256-GCM / Session TTL / 队列有界 / bash kill-wait

| 模块 | 状态 |
|------|------|
| 核心契约 (types/events/exceptions) | ✅ 完成 |
| 配置与日志系统 + 原子写 | ✅ 完成 |
| 消息路由 (Router + Rules) | ✅ 完成 |
| Gateway (EventBus/Session/User/Lock) | ✅ 完成 + TTL + 二级索引 |
| 门控系统 (Gating/Focus/IdleBackoff) | ✅ 完成 + AgentConfig.gating 覆盖 |
| System Prompt 组装器 + 注入器 | ✅ 完成 |
| Agent Loop (LLM 循环 + Hooks + 重试/回退) | ✅ 完成 + tool_calls 消息序列 |
| OneBot v11 适配器 (QQ) | ✅ 完成 (反向 WebSocket) |
| 工具系统 (ToolRegistry/ToolPermission) | ✅ 完成 + 内置命令接入 |
| 记忆系统 (MetadataStore+FTS5+BM25) | ✅ 完成 (Vector/Graph 仍 experimental) |
| 人格系统 (Persona/Mood/Drift) | ✅ 完成 (BehaviorLearner 接入) |
| 插件生态 (AstrBot/MaiBot/Native) | ✅ 完成 + PluginManager 接入 main |
| 控制面 (Admin API/MCP/Webhooks) | ✅ 完成 + 审计 + 持久化恢复 |
| 监控告警 (Metrics/Alerting) | ✅ 完成 + 接入主链路 |
| WebUI (Vanilla JS) | ✅ 完成 + sessionStorage |
| Docker 部署 + CI 门禁 | 🟡 Dockerfile/compose 完成, CI cov-fail-under 进行中 |
| 真实 LLM Provider | ✅ 完成 (OpenAICompatProvider httpx) |
| 安全基线 | ✅ K7 完成 |

---

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 安装

```bash
git clone https://github.com/EchoAI-01/ISAC.git
cd ISAC
uv sync --all-extras --dev
```

### 启动（开发模式，无需真实 LLM 或 QQ）

```bash
# 创建最小配置
mkdir -p data
echo '{"config_version": "1.0.0", "debug": false}' > data/config.jsonc

# 启动（使用内置 StubProvider，不调用外部 LLM）
uv run python -m isac
```

启动后会创建名为 `default` 的默认 Agent 并开始运行。此时无 Channel 连接，
应用处于就绪等待状态。

### 接入真实 LLM

编辑 `data/config.jsonc`：

```jsonc
{
    "config_version": "1.0.0",
    "llm": {
        "provider": "openai_compat",
        "model": "gpt-4o-mini",
        "api_key": "sk-...",
        "base_url": "https://api.openai.com/v1"
    }
}
```

`OpenAICompatProvider` 正在开发中（后续将作为 Provider 主链路前置节点补齐），当前使用 `StubProvider` 占位。

### 接入 QQ (OneBot)

1. 安装 OneBot 依赖：`uv sync --extra onebot`
2. 配置 `data/config.jsonc`：

```jsonc
{
    "channels": {
        "onebot": {
            "enabled": true,
            "host": "127.0.0.1",
            "port": 8080,
            "access_token": ""
        }
    },
    "bot_id": "你的QQ号"
}
```

3. 在 NapCat 中配置反向 WebSocket 连接到 `ws://127.0.0.1:8080`

---

## 文档导航

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 架构设计 — 系统拓扑、组件职责、消息生命周期、ADR 决策记录 |
| [DEVELOP.md](./DEVELOP.md) | 开发指南 — 编码规范、模块开发流程、导入规则、测试编写 |
| [SPECIFICATION.md](./SPECIFICATION.md) | 技术规范 — 数据模型 (ISACMessage/Session/Context)、接口契约 (ABC)、配置规范 |
| [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) | 开发计划 — 节点制 SOW/TODO、当前进度、依赖关系 |
| [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md) | 拟人化运行时 — ConversationRuntime、wait、主动任务、打断、上下文恢复 |
| [MEMORY_DESIGN.md](./MEMORY_DESIGN.md) | 记忆系统 — 身份归一、写入/检索/注入/治理、无 embedding 模式 |
| [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md) | 路由与 Agent Mesh — 旁听 Agent、handoff、ACL、上下文边界 |
| [PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md) | 插件兼容 — AstrBot / MaiBot / Native SDK 兼容范围、权限与测试 |
| [CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md) | 控制面规范 — REST API、MCP Server、Webhook、认证、审计 |
| [AGENTS.md](./AGENTS.md) | Agent 协作指南 — 给接手开发的 Agent 看的一页纸上下文 |

---

## 技术栈

| 层级 | 选型 |
|------|------|
| 语言 | Python 3.12+ (async/await) |
| 包管理 | uv |
| LLM 协议 | OpenAI 兼容 API (自定义 base_url) |
| 记忆存储 | sqlite-vec (向量) + SQLite FTS5 (全文) |
| 嵌入模型 | fastembed (本地) / OpenAI Embedding API |
| 重排序 | bge-reranker / Cohere Rerank / Jina Rerank |
| QQ 适配 | aiocqhttp (OneBot v11, 反向 WebSocket) |
| 日志 | structlog (结构化, stdlib 降级) |
| 控制面 | FastAPI + uvicorn |
| 测试 | pytest + pytest-asyncio + pytest-cov |

---

## 目录结构

```
isac/
├── core/           # 核心契约：类型、事件、异常、常量、注入器 ABC
├── utils/           # 基础设施：配置加载、日志、安全
├── provider/        # LLM/嵌入/重排序 提供商抽象
├── memory/          # 记忆系统：检索流水线、存储引擎、注入器
├── persona/         # 人格系统：配置管理、情绪、行为学习
├── agent/           # Agent 核心：循环、Hooks、Prompt 组装、注入器、工具
├── gating/          # 门控系统：回复必要性评分、IdleBackoff、FocusMode
├── router/          # 消息路由：绑定匹配、触发词、默认 Agent
├── gateway/         # 消息网关：事件总线、会话管理、用户映射、并发锁
├── channel/         # 平台适配器 (OneBot / 预留 Telegram / Discord 等)
├── commands/        # 用户命令系统 (/mute, /focus, /agents)
├── plugin/          # 插件生态：AstrBot/MaiBot 兼容层、原生 SDK
├── runtime/         # 运行时：AgentManager、实例组装、配置、Agent 互联总线
├── control/         # 控制面：Admin REST API、MCP Server、Webhooks
├── locales/         # 多语言 (zh_CN / en_US)
└── main.py          # 应用入口：组装所有组件 + 依赖注入
```

---

## 开发

```bash
uv sync --all-extras --dev   # 安装依赖
uv run ruff check .          # Lint (line-length 120)
uv run mypy isac/            # 类型检查
uv run pytest                # 运行测试 (asyncio_mode=auto)
uv run python -m isac        # 启动
```

---

## 许可

MIT License — 详见 [LICENSE](./LICENSE)

## 参考与致谢

ISAC 的设计融合了以下项目的优秀思想：

- **AstrBot** — 多平台 Channel 适配器架构与 Star 插件系统
- **MaiBot** — 门控决策（回复必要性/IdleBackoff/FocusMode）与插件 Action/Command 模型
- **openclaw / opencode** — 多 Agent 运行时管理与控制面分离思路
- **hermes-agent** — Agent 工具链与自主循环模式
