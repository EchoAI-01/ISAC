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

**Release Candidate v1.0.0-rc.1** — 定位为 **"主链路 MVP + 待激活子系统"**：单/多 Agent 基础回复链路、门控、命令、路由、控制面、监控、安全基线已在生产路径运行；部分子系统核心逻辑与单测已完成，但**默认关闭或尚未接入生产消息主链路**（下表用三态标注，与 `AGENTS.md §剩余工作` / `docs/PROGRESS.md` 口径一致）。

A-K + L/M/N/O 各节点完成度（核心逻辑 + 单测口径；主链路接线状态见状态表）:

- A-I 文档冻结 / 基础骨架 / 连接路由 / 单 Agent 核心 / 多 Agent 运行时 / 插件生态 / 控制面 / 平台扩展 / 生产化交付 — 100%
- J 模型能力、计量与管理面 (J1 用量计量 + J2 多模态 Provider + J3 WebUI v2 + J4 SubAgent Runtime) — 100%
- K 稳定化 (K1-K8 CI/Docker/Playwright) — 100%
- L 拟人化运行时 / M 路由与 Agent Mesh / N 记忆深化 / O 企业化 — 核心逻辑 + 单测已交付；主链路接线按 P 节点推进（部分已在 CR3 修复轮接线，见下表）

状态图例：**✅ 已接线** = 生产主链路真实运行 ·**⚙ 配置启用** = 已接线，默认关闭需配置开启 · **🔨 待接线** = 实现+单测完成，生产路径无调用点

| 模块 | 状态 |
|------|------|
| 核心契约 (types/events/exceptions) | ✅ 已接线 |
| 配置与日志系统 + 原子写 (含目录 fsync) | ✅ 已接线 |
| 消息路由 (Router + Rules) | ✅ 已接线；MeshRouter observer/candidate 🔨 待接线 (P2) |
| Gateway (EventBus/Session/User/Lock/IdentityResolver) | ✅ 已接线 + TTL + 跨平台归一 |
| 门控系统 (Gating/Focus/IdleBackoff + LRU 会话回收) | ✅ 已接线 + AgentConfig.gating 覆盖 |
| 拟人化运行时 (ConversationRuntime/debounce/wait/interrupt/recovery) | ⚙ `conversation.enabled` 默认关闭；wait/interrupt 循环级联动 🔨 待接线 (P1) |
| 主动任务 (ProactiveScheduler, 冷却按会话隔离) | 🔨 待接线 (P1; 生产中未实例化) |
| System Prompt 组装器 + 注入器 (含 Interrupt/Recovery) | ✅ 已接线 |
| Agent Loop (LLM 循环 + Hooks + 重试/回退 + 工具调用) | ✅ 已接线；流式(streaming) 分片合并已修复但主链路未启用流式 |
| OneBot v11 适配器 (QQ) | ✅ 已接线 (反向 WebSocket) |
| 工具系统 (ToolRegistry/ToolPermission + 4 A2A 工具 restricted) | ✅ 已接线 + 内置命令；A2A 工具依赖的 mesh_action_broker 🔨 待接线 (P2) |
| 记忆系统 — FTS5+BM25 稀疏检索 + 治理 + 审计归因 | ⚙ `memory.enabled` 默认关闭 |
| 记忆系统 — 稠密(向量)召回 + RRF 融合 | ⚙ 配置 `memory.embedding` (api_key+model) 后启用 (CR3-H3 已接线) |
| 人格系统 (Persona/Mood/Drift) | ✅ 已接线 (BehaviorLearner) |
| 插件生态 (AstrBot/MaiBot/Native + on_load 生命周期) | ✅ 加载与 on_load 已接线；⚠ 默认加载路径**无进程隔离**（仅可信插件, 见 plugins/README.md）|
| 插件进程级隔离 (PluginIsolationHost 子进程真实加载) | ⚙ 机制可用 (load_plugin)；默认加载路径接管 🔨 待接线 |
| 控制面 (Admin API/MCP/Webhooks + Memory 治理 + Sessions/Events 路由) | ✅ 已接线 + 审计 + 持久化恢复 + 自动化创建受限沙箱 |
| 多租户隔离 (TenantIsolationGuard + 数据面租户谓词/命名空间前缀) | ⚙ `tenancy.enabled` 默认关闭 (CR3-L2 已接线) |
| Workflow 编排 (多入口 + fan-in 汇合 + 条件/重试 + 持久化) | 🔨 待接线 (生产中未实例化) |
| 监控告警 (Metrics/Alerting) | ✅ 已接线 |
| WebUI v2 (SPA 十域 + 配置编辑事务 + SSE) | ✅ 已接线 + Playwright |
| Docker 部署 + CI 门禁 (Playwright + release_checklist) | ✅ K8 完成 |
| 真实 LLM Provider (OpenAICompatProvider httpx + SSE + Tool Call) | ✅ 已接线 |
| 安全基线 (K7 + CR3: SSRF 请求期固定 / 非 ASCII Token 401 / restricted 创建) | ✅ 已接线 |

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

配置了 `llm.provider` 与 `llm.api_key` 后即启用真实的 `OpenAICompatProvider`（httpx + SSE + Tool Call）；未配置任何 Provider 时回退到内置 `StubProvider` 作为开发态兜底。真实模型不可达时由 `chat_with_retry` 走降级回复。

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
| [docs/](./docs/README.md) | 文档导航 — 架构、规范、使用、部署、进度的统一入口 |
| [REQUIREMENTS.md](./docs/REQUIREMENTS.md) | 统一需求清单 — 多 Agent、多 IM、拟人化、模型、控制面、稳定性与 SubAgent |
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 架构设计 — 系统拓扑、组件职责、消息生命周期、ADR 决策记录 |
| [DEVELOP.md](./docs/DEVELOP.md) | 开发指南 — 编码规范、模块开发流程、导入规则、测试编写 |
| [SPECIFICATION.md](./docs/SPECIFICATION.md) | 技术规范 — 数据模型 (ISACMessage/Session/Context)、接口契约 (ABC)、配置规范 |
| [DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md) | 开发计划 — 节点制 SOW/TODO、依赖关系 |
| [PROGRESS.md](./docs/PROGRESS.md) | 进度总表 — 各节点唯一进度事实源 |
| [HUMANLIKE_RUNTIME.md](./docs/HUMANLIKE_RUNTIME.md) | 拟人化运行时 — ConversationRuntime、wait、主动任务、打断、上下文恢复 |
| [MEMORY_DESIGN.md](./docs/MEMORY_DESIGN.md) | 记忆系统 — 身份归一、写入/检索/注入/治理、无 embedding 模式 |
| [ROUTING_AND_AGENT_MESH.md](./docs/ROUTING_AND_AGENT_MESH.md) | 路由与 Agent Mesh — 旁听 Agent、handoff、ACL、上下文边界 |
| [PLUGIN_COMPATIBILITY.md](./docs/PLUGIN_COMPATIBILITY.md) | 插件兼容 — AstrBot / MaiBot / Native SDK 兼容范围、权限与测试 |
| [CONTROL_PLANE_SPEC.md](./docs/CONTROL_PLANE_SPEC.md) | 控制面规范 — REST API、MCP Server、Webhook、认证、审计 |
| [CODE_REVIEW_REPORT.md](./docs/CODE_REVIEW_REPORT.md) | 已修复缺陷追溯档案 — 源码 `#N` 引用锚点 |
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
