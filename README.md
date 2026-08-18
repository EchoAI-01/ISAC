# ISAC — Intelligent Social AI Companion

> 下一代多 Agent AI 社交陪伴 Bot 框架 — 把「AI 社交陪伴」拆成可组合、可替换、可按配置定制的独立子系统。

`v1.0.0-rc.1` · Python 3.12+ · 1568 单元/集成测试通过 · ruff / mypy 全绿 · MIT License

---

## ISAC 是什么

ISAC 是一个用 Python 编写的**多 Agent AI 社交陪伴 Bot 框架**。它不只是"收到消息 → 调 LLM → 回一句"的脚手架，而是把一个像人一样聊天的 Bot 所需的能力，拆成四层独立的流水线：

- **门控决策** — 要不要回？（避免每条消息都消耗 token）
- **记忆检索** — 该记得什么？（越聊越熟）
- **人格注入** — 用什么风格回？（情绪、表达习惯、注意力漂移）
- **多 Agent 路由** — 哪个 Agent 回？（一个账号背后可以有多个性格各异的 Agent）

每一层都能独立替换或扩展，Bot 的行为通过**配置文件**定制，多数场景无需改代码。

**适合谁**：想搭建拟人化陪伴 Bot、多角色群聊 Bot，或需要一个可插拔、可观测、带控制面的 Agent 运行时的开发者。

---

## 核心特性

- **门控先于 Agent** — 调用 LLM 前先评定回复必要性，无需回复的消息不进入昂贵的推理链路。
- **拟人化运行时** — 消息合并（debounce）、等待、主动发起话题、思考期打断、上下文恢复，让节奏更像真人。
- **记忆系统** — FTS5+BM25 稀疏检索 / 向量稠密召回 / 图谱召回三路融合，配合记忆治理与"越聊越熟"的写入回路。
- **多 Agent 单进程** — 多个 Agent 共享 Provider 连接池与嵌入模型，单进程运行，资源占用低。
- **Agent 协作显式化** — Agent 默认互不相通，需显式授权（ACL）才能互相委托任务。
- **多平台适配** — OneBot v11（QQ）已就绪，飞书 / QQ 官方机器人可配置启用，Telegram / Discord / WebChat 等预留接口。
- **控制面/数据面分离** — Admin REST API、MCP Server、WebUI v2 独立于消息处理链路，控制面异常不影响发消息。
- **生产化基线** — 结构化日志、指标监控、用量计量、SSRF 防护、Docker 部署、CI 门禁一应俱全。

---

## 架构总览

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

### 关键设计决策

| 设计 | 说明 |
|------|------|
| **门控先于 Agent** | 调用 LLM 前先由门控系统评定回复必要性；无需回复的消息不消耗 token |
| **Channel 与 Agent 解耦** | 一个 QQ 号可服务多个 Agent，消息由 Router 按绑定/触发词/默认规则分发 |
| **多 Agent 单进程** | 多个 Agent 实例在单进程内运行，共享 Provider 连接池与嵌入模型，降低资源消耗 |
| **Agent 互联显式化** | InterAgentBus + ACL 链路，Agent 默认不互通，需显式授权才能 `ask_agent()` |
| **控制面/数据面分离** | 消息处理链路（数据面）与 Admin API / MCP Server（控制面）解耦；控制面崩溃不影响发消息 |
| **拟人表达靠 Prompt，拟人行为靠 Runtime** | 表达风格/情绪/记忆通过 System Prompt 注入；回复节奏/等待/主动/打断由 ConversationRuntime 管理 |
| **兼容存量插件** | 桥接 AstrBot Star 与 MaiBot 插件系统，同时提供 ISAC Native SDK 承载独有能力 |

架构细节、组件职责与 ADR 决策记录见 [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

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

启动后会创建名为 `default` 的默认 Agent 并进入就绪等待状态。此时无 Channel 连接，可用于验证进程与配置。

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

> 更多平台（飞书 / QQ 官方 / WebChat）与记忆、门控、人格的完整配置项，见 [docs/SPECIFICATION.md](./docs/SPECIFICATION.md) 配置规范。

---

## 功能与状态

ISAC 定位为 **"主链路 MVP + 待激活子系统"**：单/多 Agent 基础回复链路、门控、命令、路由、控制面、监控、安全基线已在生产路径稳定运行；拟人化运行时、Agent Mesh、记忆治理、身份归一、Workflow、飞书/QQ 官方适配器等子系统的核心逻辑与单测已完成，多数**默认关闭、需按配置开启**。

状态图例：**✅ 已接线**（生产主链路真实运行）· **⚙ 配置启用**（已接线，默认关闭）· **🔨 骨架**（实现待完善或生产路径无调用点）

| 模块 | 状态 |
|------|------|
| 核心契约 / 配置与日志 / 原子写 | ✅ 已接线 |
| 消息路由（Router + Rules + MeshRouter） | ✅ 已接线 |
| Gateway（事件总线 / 会话 / 用户映射 / 身份归一 / 并发锁） | ✅ 已接线 |
| 门控系统（Gating / Focus / IdleBackoff） | ✅ 已接线 |
| System Prompt 组装器 + 注入器 | ✅ 已接线 |
| Agent Loop（LLM 循环 + Hooks + 重试/回退 + 工具调用） | ✅ 已接线（主链路默认非流式） |
| 人格系统（Persona / Mood / Drift / BehaviorLearner） | ✅ 已接线 |
| OneBot v11 适配器（QQ，反向 WebSocket） | ✅ 已接线 |
| 记忆系统 — FTS5+BM25 稀疏检索 + 治理 + 审计归因 | ⚙ `memory.enabled` |
| 记忆系统 — 稠密（向量）召回 + RRF 融合 | ⚙ `memory.embedding` |
| 记忆系统 — 图谱召回（mentioned_in 提及图 + Reranker） | ⚙ `memory.graph_recall.enabled` |
| 拟人化运行时（debounce / wait / interrupt / recovery） | ⚙ `conversation.enabled` |
| 主动任务（ProactiveScheduler + 生产者） | ⚙ `conversation.proactive.*` |
| 记忆整合后台任务（MemoryConsolidator） | ⚙ `memory.consolidation.enabled` |
| 飞书 / QQ 官方适配器（Webhook + AES/Ed25519 验签） | ⚙ `channels.feishu` / `channels.qq_official` |
| 身份归一控制面（bind / conflicts / resolve） | ⚙ `identity.enabled` |
| 多租户隔离（TenantIsolationGuard） | ⚙ `tenancy.enabled` |
| Workflow 编排（多入口 + fan-in + 条件/重试 + action_handler） | ⚙ `control.workflow.enabled` |
| 工具系统（ToolRegistry / ToolPermission + A2A 工具） | ✅ 已接线 |
| 控制面（Admin API / MCP / Webhooks + 审计 + 持久化恢复） | ✅ 已接线 |
| WebUI v2（SPA 十域 + 配置编辑事务 + SSE） | ✅ 已接线 |
| 监控告警（Metrics / Alerting）+ 模型用量计量 | ✅ 已接线 |
| 真实 LLM Provider（OpenAICompatProvider） | ✅ 已接线 |
| 安全基线（SSRF + CGNAT 拦截 / Token 认证 / restricted 创建） | ✅ 已接线 |
| 微信适配器（公众号 / 企业微信） | 🔨 骨架 |
| 插件进程级隔离（默认加载路径接管） | 🔨 骨架 |

> 各节点唯一进度事实源见 [docs/PROGRESS.md](./docs/PROGRESS.md)。

---

## 开发计划 (Roadmap)

ISAC 采用**节点制**推进（A/B/C… 里程碑 + P 主链路接线 + Q MVP 收尾 + T 开箱可用 + FE 前后端分离，当前**后端先行**）。当前进展：

### ✅ 已完成

- **A–I 基础体系** — 文档冻结、基础骨架、连接与路由、单/多 Agent 核心运行时、插件生态、控制面与自动化、平台与工具扩展、生产化交付。
- **J 模型能力、计量与管理面** — 用量计量、多模态 Provider、WebUI v2、SubAgent Runtime。
- **K 稳定化** — 应用生命周期、真实 Provider、存储生命周期、配置持久化恢复、端到端集成测试、安全基线、CI/Docker/Playwright 发布准入。
- **P0–P2 主链路接线** — 消息处理并发化、拟人化运行时激活、Agent Mesh 激活。
- **Q0–Q2 MVP 收尾** — 开箱可触达、记忆写入回路与身份稳定化（"聊 → 重启 → 检索命中"闭环）、人格差异化。
- **T1/T2/T4 开箱可用** — 开箱能对话（私聊无条件触发 + 未回复可观测）、零配置启动（默认配置内置）、错误可诊断（中文可操作提示 + `/health` + 实时日志台后端），均经真机冒烟验证（2026-08-04）。

### ⚙ 已实现，默认关闭待打磨

- **P3 记忆检索深化** — 图谱召回（mentioned_in 提及图）+ Reranker 已激活；通用实体关系图待完善。
- **P4 身份归一** — 控制面 bind/conflicts/resolve 已激活；跨平台身份聚合持续打磨。
- **P5 Workflow** — action_handler + 声明式加载 + 条件求值已激活；租户隔离模式与 Agent 工具入口待接线。
- **平台适配器** — 飞书（AES-256-CBC）、QQ 官方（Ed25519）真实收发已实现，默认关闭。

### ✅ 后端收尾（2026-08-16）

- **T6 插件市场与热重载** — 四源安装（market/git/url/upload）+ 热重载同步运行中 Agent + 失败重试；R3 插件与 MCP 生态激活。
- **R1–R6 功能广度轮** — 多模态出入站闭环与计量、控制面与 SubAgent 收尾、记忆完整性（行话学习 + COMPRESS 压缩）、Session 持久化 + SecretStore、企业化激活（租户控制面）。
- **前后端分离后端段** — OpenAPI 契约冻结 + CORS/跨源认证 + 控制面开箱（control 默认开 + 首登强制设密码 + 配置 Schema 端点）。

### ✅ 质量清偿（2026-08-18）

- **三轮全量代码审查修复** — N1b/N1c/N1d 同规格 5 路并行全量审查 + 主审逐条回码复核，累计 Fix-37~137：含沙箱逃逸、协议契约、会话内核竞态、注入防护、资源边界卫生等，Critical/Major/Minor 全部代码级清零。
- **N1e 全局配置持久化 + 热重载** — 控制面 `GET/PATCH /config/global` + reload 端点（override 覆盖层不破坏 config.jsonc 注释 + If-Match 乐观锁 + applied/restart_required 区分），全局 `mcp.servers` 等定义不再"手编 + 重启"。
- 当前全量 2098 测试通过，ruff/mypy 全绿，红线（U9 只减不增指标）全绿。

### 🔨 规划中

- **环境准入项** — Docker 冒烟、browser CI 复核、release checklist、24h soak（见 DEVELOPMENT_PLAN §三之三 N2）。
- **T5 真实 IM 接入验收** — 需用户凭据；OneBot/飞书/QQ 官方/企业微信逐个真机联调。
- **前端轨道 F1–F4** — 独立项目，围绕冻结的 API 契约开发（登录/setup 向导 → 十域页面 → 实时日志 → 插件市场 UI）。
- **O4 平台扩展剩余** — 微信公众号（mp）模式（wecom 企业微信已实现）。
- **O5 多模态** — 视频 Provider 真实端点（选型中）。
- **流式主链路** — 流式分片合并已修复，主链路启用流式待评估。

> 发布门：**v1.0 可对话**（T1+T2 ✅）→ **可管理**（后端段 ✅，前端 F1/F2 进行中）→ **可接入**（+T5）→ **可扩展**（R3+T6 ✅）→ **GA**（环境准入 + 前端 F2）。完整 SOW / 依赖关系见 [docs/DEVELOPMENT_PLAN.md](./docs/DEVELOPMENT_PLAN.md)（含 §三之三 下一步行动计划），里程碑见 [docs/ROADMAP.md](./docs/ROADMAP.md)。

---

## 目录结构

```
isac/
├── core/            # 核心契约：类型、事件、异常、常量、注入器 ABC
├── utils/           # 基础设施：配置加载、日志、安全 (SSRF)
├── provider/        # LLM/嵌入/重排序/多模态 (image_gen/stt_tts/video_gen) 提供商抽象
├── memory/          # 记忆系统：检索流水线、存储引擎、注入器、治理、图谱召回、整合
├── persona/         # 人格系统：配置管理、情绪、行为学习
├── agent/           # Agent 核心：循环、Hooks、Prompt 组装、注入器、工具、SubAgent
├── gating/          # 门控系统：回复必要性评分、IdleBackoff、FocusMode
├── router/          # 消息路由：绑定匹配、触发词、默认 Agent、MeshRouter
├── gateway/         # 消息网关：事件总线、会话管理、用户映射、身份归一、并发锁
├── channel/         # 平台适配器 (OneBot / 飞书 / QQ 官方 / 微信骨架 / 预留 Telegram·Discord)
├── commands/        # 用户命令系统 (/mute, /focus, /agents)
├── plugin/          # 插件生态：AstrBot/MaiBot 兼容层、原生 SDK、进程级隔离宿主
├── runtime/         # 运行时：AgentManager、实例组装、拟人化运行时、租户隔离、Agent 互联总线
├── control/         # 控制面：Admin REST API、MCP Server、Webhooks、WebUI v2、Workflow 编排
├── observability/   # 监控告警：Metrics/Alerting + 模型用量计量 (usage)
├── artifacts/       # 多模态制品存储：本地 FS + SQLite 元数据 + 原子写
├── locales/         # 多语言 (zh_CN / en_US)
└── main.py          # 应用入口：组装所有组件 + 依赖注入
```

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
| 多模态 | OpenAI 兼容 image_gen / stt_tts / video_gen Provider (按 ModelDescriptor 路由) |
| QQ 适配 | aiocqhttp (OneBot v11, 反向 WebSocket) |
| 日志 | structlog (结构化, stdlib 降级) |
| 控制面 | FastAPI + uvicorn |
| 测试 | pytest + pytest-asyncio + pytest-cov |

---

## 参与开发

```bash
uv sync --all-extras --dev   # 安装依赖
uv run ruff check .          # Lint (line-length 120)
uv run mypy isac/            # 类型检查
uv run pytest                # 运行测试 (asyncio_mode=auto)
uv run python -m isac        # 启动
```

编码规范、模块开发流程、导入规则与测试编写见 [docs/DEVELOP.md](./docs/DEVELOP.md)。

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

## 许可

MIT License — 详见 [LICENSE](./LICENSE)

## 参考与致谢

ISAC 的设计融合了以下项目的优秀思想：

- **AstrBot** — 多平台 Channel 适配器架构与 Star 插件系统
- **MaiBot** — 门控决策（回复必要性/IdleBackoff/FocusMode）与插件 Action/Command 模型
- **openclaw / opencode** — 多 Agent 运行时管理与控制面分离思路
- **hermes-agent** — Agent 工具链与自主循环模式
