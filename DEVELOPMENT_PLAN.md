# ISAC 开发计划

> 按天分解的可执行开发计划
> 节奏: 全职 (每天 6-8 小时)
> 第一平台: QQ (OneBot)
> Provider: OpenAI 兼容 API (支持自定义 base_url)
> 架构基线: ARCHITECTURE.md v3.0 (多 Agent / 路由 / 互联 / 控制面)

---

## 总览

| Phase | 周期 | 工作日 | 目标 |
|-------|------|--------|------|
| Phase 1: Foundation | 第 1-2 周 | 10d | 可运行的 Bot，QQ 收发消息 + LLM 回复 |
| Phase 2: Core (单 Agent) | 第 3-6 周 | 20d | 完整 Agent + 记忆 + 门控 + 拟人 |
| Phase 3: Multi-Agent | 第 7-9 周 | 15d | 多 Agent 运行时 + 路由 + 互联 + 启用矩阵 |
| Phase 4: Ecosystem | 第 10-14 周 | 25d | AstrBot/MaiBot 插件兼容 + 原生 SDK v2 + 多平台 + MCP |
| Phase 5: Polish & Control Plane | 第 15-18 周 | 20d | 控制面 (Admin API/MCP/Webhook) + 生产可用 |

**总计**: 约 18 周 (90 个工作日)，含缓冲约 **21-23 周**

> **工时说明**: 预估工时为纯开发时间，实际交付需乘以 **1.3~1.5** 的缓冲系数
> （含调试、联调、Code Review、文档更新）

---

## Phase 1: Foundation (第 1-2 周)

> 交付标准: `uv run python -m isac.main` 启动后，通过 QQ 发消息，Bot 用 LLM 回复

### Week 1: 基础设施

#### Day 1 — 项目脚手架 + 核心类型 + i18n 基础

| 时段 | 任务 | 产出 |
|------|------|------|
| 上午 | 创建项目结构、pyproject.toml、ruff 配置、.gitignore、LICENSE | `uv sync` 可运行 |
| 下午 | `core/types.py`（含 MessageStatus）+ `core/events.py` + `core/exceptions.py`（ISACError 体系）+ `core/constants.py` + `locales/` i18n 基础 | 核心数据模型、事件枚举、错误体系、本地化框架 |

**具体产出**:
```
ISAC/
├── pyproject.toml          # uv + ruff + pytest 配置
├── .gitignore              # Python + IDE + data/
├── LICENSE                 # MIT
├── isac/
│   ├── __init__.py         # 版本号
│   ├── core/
│   │   ├── types.py        # RuntimeContext, AgentContext, InjectionContext, GatingContext, MessageStatus
│   │   ├── events.py       # EventType, AgentHookPoint
│   │   ├── exceptions.py   # ISACError 体系 (SPECIFICATION.md 5.3)
│   │   └── constants.py    # 常量
│   ├── locales/
│   │   ├── __init__.py     # load_text() 工具函数
│   │   └── zh_CN.py        # 中文 (默认)
│   └── utils/
│       └── logger.py       # structlog 配置 (开发模式彩色输出)
└── tests/
    ├── conftest.py
    └── unit/
```

**验收**: `uv run pytest` 通过 (即使没有真实测试)

---

#### Day 2 — Channel 抽象 + 消息模型

| 时段 | 任务 | 产出 |
|------|------|------|
| 上午 | `channel/base.py` PlatformAdapter ABC | 适配器接口 |
| 下午 | `channel/model.py` ISACMessage + MessageSegment + `channel/registry.py` | 统一消息模型 |

**验收**: 能创建 ISACMessage 实例，PlatformAdapter 可被子类化

---

#### Day 3-5 — OneBot 适配器 + EventBus

| 时段 | 任务 | 产出 |
|------|------|------|
| Day 3 上午 | OneBot 协议研究 (aiocqhttp 库) | 协议理解 |
| Day 3 下午 | `channel/adapters/onebot/adapter.py` 连接层 | WS 连接 |
| Day 4 上午 | 消息收发 + ISACMessage 转换 | 收发消息 |
| Day 4 下午 | 单元测试 + 联调 (用 NapCat 测试) | 真实 QQ 消息收发 |
| Day 5 | `gateway/event_bus.py` Intercept + Async 双层 + 单元测试 | 事件总线 |

**验收**: 通过 NapCat 连接 QQ，能收发消息；EventBus Intercept 链按顺序执行，可阻止后续；Async 处理器并发执行

---

### Week 2: 会话管理 + Provider + 入口

#### Day 6-7 — SessionManager + UserMapper

| 时段 | 任务 | 产出 |
|------|------|------|
| Day 6 上午 | `gateway/models.py` Session (含 agent_id 字段) + UserProfile 数据模型 | 数据模型 |
| Day 6 下午 | `gateway/session.py` SessionManager (SQLite 持久化) | 会话 CRUD |
| Day 7 上午 | `gateway/user_mapper.py` 跨平台用户映射 | 同一用户多平台识别 |
| Day 7 下午 | 单元测试 + 会话并发锁 (SessionLockManager) | 并发安全 |

**验收**: 消息到达后能创建/查找 Session，同一用户从不同平台来能映射到同一 UserProfile

---

#### Day 8 — Provider + 配置 + 安全基础

| 时段 | 任务 | 产出 |
|------|------|------|
| 上午 | `provider/base.py` LLMProvider ABC + `provider/manager.py` ProviderManager + `provider/llm/openai_compat.py` | LLM 调用（含重试 + 回退模型） |
| 下午 | `utils/config.py` 配置加载 + ConfigMigrator (配置版本化) | 配置管理 |
| 下午 | `utils/security.py` API Key 加密 (AES-256-GCM) + 完善 logger (生产模式 JSON) | 安全 + 日志 |

**Provider 设计要点** (支持自定义 API):
```python
class LLMProvider(ABC):
    async def chat(...) -> LLMResponse: ...
    def chat_stream(...) -> AsyncIterator[LLMChunk]: ...

class OpenAICompatProvider(LLMProvider):
    """OpenAI 兼容 Provider，支持自定义 base_url
    可用于: OpenAI / DeepSeek / Moonshot / 任意 OpenAI 兼容 API
    """
    def __init__(self, api_key: str, base_url: str, model: str): ...

class ProviderManager:
    """Provider 管理器。

    错误处理遵循 SPECIFICATION.md 5.1/5.2:
    重试 3 次 (指数退避) → 回退到 fallback_model → 降级回复。
    """
    async def chat_with_retry(self, **kwargs) -> LLMResponse: ...
```

**ConfigMigrator 设计**:
```python
class ConfigMigrator:
    """配置版本迁移器。每次配置格式变更时添加迁移函数。"""
    MIGRATIONS: dict[str, Callable] = {}

    def migrate(self, config: dict) -> dict:
        current_version = config.get("config_version", "1.0.0")  # 初始版本与 ARCHITECTURE.md 4.1 一致
        # 按版本顺序应用迁移
        ...
```

**验收**: 能通过 OpenAICompatProvider 调用 LLM；配置带版本号；API Key 加密存储

---

#### Day 9 — main.py 应用入口 + 最简门控

| 时段 | 任务 | 产出 |
|------|------|------|
| 上午 | `main.py` 组装所有组件 + 依赖注入 | 可启动系统 |
| 下午 | `data/config.jsonc` 配置文件 + 最简门控 + 端到端联调 | QQ 消息 → LLM → 回复 |

**最简门控** (Phase 1 临时方案，Phase 2 替换为完整门控):
```python
def simple_gate(message: ISACMessage, bot_id: str) -> bool:
    """Phase 1 最简门控: @bot 或私聊才回复，避免群聊刷屏"""
    if message.group_id is None:  # 私聊
        return True
    # 群聊中检查 segments 是否有 @bot (ISACMessage 无 is_private/has_at_bot 字段)
    return any(
        seg.type == "at" and seg.data.get("user_id") == bot_id
        for seg in message.segments
    )
```

**main.py 组装逻辑** (Phase 1 临时，通过依赖注入避免模块循环依赖):
```python
async def main():
    config = load_config("data/config.jsonc")
    logger = setup_logger(config)

    event_bus = EventBus()
    session_mgr = SessionManager(config)
    user_mapper = UserMapper(session_mgr)
    llm = OpenAICompatProvider(config.llm)
    channel_registry = ChannelRegistry()

    onebot = OneBotAdapter(config.platforms.qq)

    # Phase 1 临时消息处理 (Phase 2 替换为 Agent Loop)
    async def handle_message(message: ISACMessage):
        if not simple_gate(message, bot_id=config.platforms.qq.bot_id):
            return  # 门控拒绝
        session = await session_mgr.get_or_create(message)
        response = await llm.chat(system="你是 ISAC", messages=[...])
        await onebot.send(build_reply(message, response.content))  # 构造回复 ISACMessage

    onebot.on_message = handle_message
    channel_registry.register(onebot)
    await channel_registry.start_all()
```

**验收**: 启动后在 QQ 发消息，Bot 能用 LLM 回复；群聊中只有 @bot 才回复

---

#### Day 10 — 测试 + CI + 周回顾

| 时段 | 任务 | 产出 |
|------|------|------|
| 上午 | 补充单元测试 (Phase 1 模块覆盖率 ≥ 60%；Phase 2 核心模块需达 ≥ 80%，见 DEVELOP.md 5.2) | 测试套件 |
| 下午 | GitHub Actions CI (ruff + mypy + pytest) | CI 流水线 |
| 下午 | 周回顾: 检查覆盖率、更新文档、评估进度 | 回顾记录 |

**验收**: `pytest --cov` 通过，CI 绿灯

---

## Phase 2: Core (第 3-6 周)

> 交付标准: Bot 能记住用户、拟人化回复、知道何时说话、使用社交工具

### Week 3: Agent Loop + Prompt Builder

#### Day 11 — AgentHooks + PromptInjector 基类

- `agent/hooks.py` AgentHooks + AgentHookPoint
- `agent/injector.py` PromptInjector ABC
- 单元测试

#### Day 12-13 — SystemPromptBuilder

- Day 12: `agent/prompt_builder.py` 核心逻辑 (注册、排序、频率控制、预算裁剪)
- Day 13: 内置注入器 `agent/injectors/base_identity.py` + `tools_available.py`
- 单元测试 (频率控制、预算裁剪、空注入)

#### Day 14-15 — ISACAgentLoop + 工具系统

- Day 14 上午: `agent/loop.py` 主循环 + `_call_llm` (流式/非流式)
- Day 14 下午: 工具执行 + 错误处理 (ToolError / Exception)
- Day 15: `agent/tools/registry.py` + `agent/tools/base.py` + **工具权限控制** + 集成测试
- **替换** main.py 中的临时消息处理为 Agent Loop

**工具权限控制** (来自 DEVELOP.md 七、安全规范):
```python
class ToolPermission:
    """工具权限检查"""
    DEFAULT_POLICY = {
        "send_emoji": "allow",
        "send_image": "allow",
        "query_memory": "allow",
        "web_search": "allow",
        "read_file": "restricted",  # 限制在项目目录
        "write_file": "restricted",
        "bash": "deny",             # 默认禁用
    }
```

**验收**: Agent Loop 能执行多轮工具调用，流式回复工作正常，工具权限生效

---

### Week 4: 门控 + 记忆存储

#### Day 16-17 — 门控系统

- Day 16: `gating/reply_necessity.py` (评分模型) + `gating/types.py`
- Day 17 上午: `gating/turn_scheduler.py` + `gating/turn_gates.py`
- Day 17 下午: `gating/idle_backoff.py` + `gating/system.py` (含 FocusMode)
- **替换** Day 9 的最简门控为完整门控系统

**验收**: 群聊中 Bot 不会每条都回复，@bot 时必定回复，空闲后指数退避，FocusMode 激活时积极参与

#### Day 18-19.5 — 记忆存储引擎

- Day 18: `memory/storage/metadata.py` (SQLite + FTS5) + Schema 初始化 (记忆表含 agent_id 命名空间)
- Day 19 上午: `memory/storage/vector.py` (sqlite-vec)
- Day 19 下午: `memory/storage/sparse.py` (BM25)

**验收**: 能存储/检索 Episode，向量搜索工作，FTS5 全文搜索工作

#### Day 19.5-20.5 — EmbeddingManager

- 1.5 天: `memory/embedder.py` EmbeddingManager
- 支持 fastembed (本地) + OpenAI 兼容 API
- 降级机制 (模型不可用时降级到纯稀疏搜索)
- 嵌入指纹 (用于向量一致性检查)

**验收**: 文本能被向量化，维度可配置，降级机制工作

---

### Week 5: 记忆检索 + 注入 + 编码

#### Day 21-22 — MemoryRetrievalPipeline

- Day 21: `memory/pipeline.py` 检索流水线 (Embed → Dense + Sparse → RRF → Rerank)
- Day 22 上午: `memory/reranker.py` (bge-reranker + API) + RRF Fusion 集成
- Day 22 下午: `memory/storage/graph.py` (最小实现: 用户-群-话题关系边) + 集成测试

**验收**: 给定查询，能返回 Top-K 相关记忆，重排序提升精度

#### Day 23 — HeuristicMemoryInjector

- `memory/injector/heuristic.py`
- LLM 生成聊天印象 → 用印象搜记忆 → 格式化注入
- 频率控制 (3 分钟冷却 + 60 条新消息)

**验收**: 长对话后能自动注入相关记忆到 System Prompt

#### Day 24 — PersonProfileInjector

- `memory/injector/person_profile.py`
- 识别对话参与者 → 拉取画像 → 注入
- `【人物画像-内部参考】` 格式

**验收**: 跟已知用户对话时，Bot 能"认出"对方

#### Day 25-25.5 — MidTermMemory + JargonInjector + MemoryEncoder

- Day 25 上午: `memory/injector/mid_term.py` (CompressionPolicy + Summary + Recall Cue)
- Day 25 下午: `memory/injector/jargon.py` (行话检测 + 解释注入)
- Day 25.5 上午: `memory/consolidator.py` (后台整合: 去重/合并/剪枝)
- Day 25.5 下午: **MemoryEncoder** (作为 POST_TOOL/FINAL_RESPONSE hook 注册):
  - 对话结束后异步存储 Episode
  - 更新 PersonProfile
  - 更新 Jargon

**验收**: 长对话压缩后能保留关键信息，行话能被检测和解释，对话结束后记忆被存储

---

### Week 6: 工具 + 人格 + 集成

#### Day 26-27 — 社交工具

- Day 26: `send_emoji.py` + `send_image.py` + `query_memory.py`
- Day 27: `query_person_profile.py` + `switch_chat.py` + `wait.py` + `fetch_history.py` + `view_forward_message.py`
- 每个工具的 System Prompt 人格指令

**验收**: Bot 能在回复中发表情、查记忆、切换话题

#### Day 28-29 — 人格配置

- Day 28: `persona/drift_profiles.py` (subtle/active/scattered/wild) + `persona/style_profiles.py`
- Day 29: `persona/mood.py` (情绪状态模型) + `persona/manager.py` + `persona/behavior_learner.py` (注册 FINAL_RESPONSE hook) + 补充 `locales/en_US.py`
- 注入器 (位于 `agent/injectors/`，读取 `persona/` 配置): `attention_drift.py` + `expression_style.py` + `mood.py` + `skill_selector.py`
  - 注: `persona/mood.py` 负责情绪状态计算，`agent/injectors/mood.py` 负责将其注入 Prompt，职责不重叠

**验收**: Bot 回复有明显的注意力漂移风格，表达风格一致

#### Day 30 — 核心集成测试 + 周回顾

- `tests/integration/test_full_flow.py` 完整消息流测试
- 记忆跨会话测试
- 门控决策测试
- 拟人效果验证 (人工)
- 周回顾: 检查覆盖率、更新文档、评估进度

**验收**: Phase 2 全部交付标准达成

---

## Phase 3: Multi-Agent (第 7-9 周)

> 交付标准: 单进程运行 2+ Agent；一个 QQ 连接服务多个 Agent (绑定/触发词/默认 Agent 路由)；Agent 间按 Link 互联；每 Agent 独立配置/记忆/插件矩阵

### Week 7: Agent Runtime

#### Day 31 — AgentConfig + 配置分层
- `runtime/config.py` AgentConfig 数据模型 (SPECIFICATION.md 1.6)
- `utils/config.py` 支持全局 + `data/agents/<id>/config.jsonc` 分层加载
- Agent 注册表 `data/agents/registry.jsonc`

#### Day 32-33 — AgentInstance 组装
- `runtime/instance.py` AgentInstance
- `runtime/assembly.py` 按 AgentConfig 组装独立子系统 (gating/prompt_builder/hooks/memory/persona)
- 记忆命名空间绑定 (agent_id / shared)
- 单元测试: 两实例互不共享可变状态

#### Day 34-35 — AgentManager
- `runtime/manager.py` 生命周期 (create/start/stop/destroy/list/reload_config)
- **重构** main.py: 单 Agent 临时组装 → AgentManager 组装 (向后兼容: 无 agents/ 时创建默认 Agent)
- 集成测试: 双 Agent 同时收发消息

**验收**: 配置两个 Agent，各自独立人格/记忆，互不影响

---

### Week 8: Message Router + Channel 解耦

#### Day 36-37 — MessageRouter
- `router/types.py` RoutingDecision / ChannelBinding / RoutingRules
- `router/router.py` 路由优先级: 显式绑定 → 触发词 → 默认 Agent → DROP
- 触发词命中后从内容剥离
- `router/rules.py` `data/routing.jsonc` 持久化 + 热更新

#### Day 38-39 — Channel 连接共享改造
- ChannelRegistry 与 Agent 解耦: 连接为共享资源
- Gateway → Router → AgentManager.handle(message, agent_id) 链路接通 (依赖注入)
- 单元测试: 同一 OneBot 连接，按触发词/默认 Agent 路由到不同 Agent

#### Day 40 — 路由集成测试 + 周回顾
- 场景: 绑定群 → 固定 Agent；触发词 → 指定 Agent；无触发词 → 默认 Agent；无默认 → DROP

**验收**: 一个 QQ 账号，两个 Agent 按规则各自回复，互不串话

---

### Week 9: Inter-Agent Bus + 启用矩阵

#### Day 41-42 — InterAgentBus
- `runtime/bus.py` InterAgentBus + Link ACL (`data/links.jsonc`)
- 消息类型: request / response / notify / handoff
- 接收方经自己的 Gating/AgentLoop 处理，System Prompt 标注来源 Agent

#### Day 43 — ask_agent 工具 + handoff
- `agent/tools/social/ask_agent.py` (经 Bus 通信，受 Link ACL 约束)
- handoff: 会话移交 (含会话摘要交接)
- 单元测试: 无 Link 拒绝、有 Link 放行、审计日志完整

#### Day 44 — 插件/工具/命令/MCP 按 Agent 启用矩阵
- AgentConfig.plugins_allow/deny、tools_policy、commands_allow、mcp_servers 生效
- Channel × Plugin 矩阵 (全局配置 plugins.channel_matrix)
- 有效权限 = Agent ∩ Channel ∩ 全局工具策略

#### Day 45 — 多 Agent 集成测试 + 周回顾
- 端到端: 2 Agent × 1 QQ 连接 + ask_agent 互联
- 覆盖率检查 (核心模块 ≥ 80%)、更新文档

**验收**: Phase 3 全部交付标准达成

---

## Phase 4: Ecosystem (第 10-14 周)

> 交付标准: AstrBot + MaiBot 插件兼容 + 原生 SDK v2 + 3 平台 + MCP

### Week 10-11: AstrBot 插件兼容

#### Day 46-47 — Star + EventType 兼容
- `plugin/compatibility/astrbot/star.py` Star 基类
- `plugin/compatibility/astrbot/events.py` EventType 映射
- **同步测试**: 开发时立即用一个简单 AstrBot 插件验证

#### Day 48-49 — Context API + FunctionTool
- `plugin/compatibility/astrbot/context.py` Context API 模拟
- `plugin/compatibility/astrbot/tools.py` FunctionTool 桥接
- **同步测试**: 用 2-3 个真实插件验证

#### Day 50 — 插件运行时
- `plugin/runtime/manager.py` + `loader.py`
- 加载/依赖解析/热重载

#### Day 51 — 沙箱 + 安全规范完善
- `plugin/compatibility/astrbot/sandbox.py` sys.meta_path 拦截
- 插件权限声明检查 (filesystem/network/env)
- 工具权限完整实现

#### Day 52-53 — 兼容性测试 + 修复
- 选 3 个简单 + 2 个复杂 AstrBot 插件测试
- 修复不兼容问题
- (开发时已同步测试，这两天主要用于复杂插件)

#### Day 54-55 — 原生插件 SDK v2
- `plugin/native/plugin.py` + `hooks.py` + `api.py`
- Plugin Manifest 扩展字段: commands / inter_agent_hooks / admin_routes(预留)
- SDK 能力: Hooks / Injectors / Tools / Commands / InterAgent Hooks / Admin Routes(预留) / Router Hook(预留)

---

### Week 12: MaiBot 插件兼容

#### Day 56-58 — MaiBot 兼容层
- `plugin/compatibility/maibot/plugin.py` Plugin 基类映射
- `plugin/compatibility/maibot/actions.py` Action → Tool / Hook
- `plugin/compatibility/maibot/commands.py` Command → ISAC Command
- 锁定 MaiBot 版本，同步用 2-3 个真实 MaiBot 插件验证

#### Day 59-60 — 三格式统一加载 + 兼容测试
- loader 自动识别 AstrBot / MaiBot / ISAC 原生格式
- 沙箱/权限体系统一
- 兼容性回归测试

---

### Week 13: 更多平台

#### Day 61-62 — Telegram 适配器
#### Day 63-64 — Discord 适配器
#### Day 65 — WebChat (WebSocket) 适配器 + 周回顾

---

### Week 14: MCP + 实用工具

#### Day 66-68 — MCP 工具集成
- `agent/tools/mcp/client.py` MCP Client
- 连接外部 MCP 服务器，按 Agent mcp_servers 矩阵生效

#### Day 69-70 — 实用工具 + 子 Agent + 周回顾
- `agent/tools/utility/` bash, read_file, write_file, web_search
- `agent/tools/utility/task.py` 子 Agent 委派

---

## Phase 5: Polish & Control Plane (第 15-18 周)

> 交付标准: 生产可用 + 控制面 (Admin API / MCP Server / Webhook) 支撑商业化自动化

### Week 15: 控制面

#### Day 71-73 — Admin REST API
- `control/api/` FastAPI: agents CRUD/启停/配置、routing rules、links、channels 绑定、插件矩阵
- `control/auth.py` Token 认证，默认 127.0.0.1
- OpenAPI 文档自动生成
- 审计日志 (操作者/动作/参数/结果)

#### Day 74 — ISAC MCP Server + Webhooks
- `control/mcp_server.py` 管理工具 (agent_create / route_set_default / link_create / message_send ...)
- `control/webhooks.py` 事件推送 + `/automation/trigger` 预留
- **验收**: 用 MCP 客户端完成 "创建 Agent → 绑定 QQ → 设为默认" 全流程

#### Day 75 — 控制面集成测试 + 周回顾

---

### Week 16: WebUI + 部署

#### Day 76-78 — WebUI 管理面板
- FastAPI 后端 + Vue 前端 (复用 Admin API)
- 多 Agent 视角: Agent 列表/配置、路由规则、互联 Link、记忆浏览

#### Day 79 — Docker 部署
- Dockerfile + docker-compose.yml (含控制面端口)
- 一键部署脚本

#### Day 80 — 更多 LLM Provider + 周回顾
- Anthropic, Google, DeepSeek 等原生 Provider

---

### Week 17: 优化 + 文档

#### Day 81-82 — 性能优化
- 多 Agent 并发、缓存、延迟分析
- 记忆检索性能优化

#### Day 83-84 — 文档完善
- 使用文档、API 文档、部署文档
- 插件开发指南 (AstrBot/MaiBot 迁移 + 原生 SDK)
- 控制面自动化指南 (商业化对接)

---

### Week 18: 收尾

#### Day 85 — 数据工具
- 数据迁移 (AstrBot / MaiBot → ISAC)
- 数据备份/导出/导入

#### Day 86 — 监控告警
- 关键指标监控 (Prometheus / Webhook)
- 控制面审计日志查看

#### Day 87-88 — 最终测试 + Bug 修复
#### Day 89-90 — 发布 v1.0

---

## 开发前的准备清单

### 已就绪 ✅
- [x] Python 3.12+ 已安装
- [x] uv 包管理器已安装
- [x] Git 仓库已创建
- [x] OpenAI 兼容 API Key + base_url 已准备

### Day 1 开始前 (无额外要求)
无需其他准备，可直接开始

### Day 3-4 开始前 (OneBot 适配器联调时)
- [ ] 安装 NapCat (QQ OneBot 实现)
- [ ] 准备一个测试 QQ 号
- [ ] 准备一个测试群
- [ ] NapCat 配置好 OneBot WebSocket

### Day 9 开始前 (端到端联调时)
- [ ] 确认 NapCat 正常运行
- [ ] 确认 LLM API 可访问

---

## 关键决策点

### Day 1 开始前必须确认

| 决策点 | 选项 | 建议 |
|--------|------|------|
| OneBot 协议版本 | OneBot v11 (aiocqhttp) vs v12 | v11 (生态更成熟) |
| 配置文件位置 | `data/config.jsonc` vs `~/.isac/config.jsonc` | `data/` (便携) |
| 数据库位置 | `data/memory/` vs `~/.isac/memory/` | `data/` (便携) |

### 开发中确认

| 决策点 | 出现时间 | 选项 |
|--------|---------|------|
| 嵌入模型选择 | Day 19.5 | fastembed (本地) vs API (OpenAI 兼容) |
| 重排序模型 | Day 22 | 本地 (bge-reranker) vs API (Cohere) vs 跳过 |
| 路由无匹配策略 | Day 36 | DROP vs 全局默认 Agent | DROP (安全)，按需配置平台默认 Agent |
| MaiBot 兼容版本 | Day 56 | 锁定当前稳定版 vs 跟踪最新 | 锁定稳定版，封装适配层 |

---

## 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|------|------|------|------|
| NapCat 协议变动 | 中 | OneBot 适配器失效 | 跟踪 NapCat 版本 |
| sqlite-vec 性能不足 | 低 | 记忆检索慢 | 预留 FAISS 切换接口 |
| AstrBot API 大改 | 低 | 兼容层失效 | 锁定兼容的 AstrBot 版本 |
| LLM Token 成本超预期 | 中 | 运行成本高 | 门控过滤 + 频率控制 + 压缩 |
| 开发进度延误 | 中 | 交付延迟 | 缓冲系数 1.3-1.5x |
| AstrBot 插件不兼容 | 中 | 兼容层工作量大 | 开发时同步测试，不等到最后 |
| MaiBot API 大改 | 中 | MaiBot 兼容层失效 | 锁定兼容版本，抽象适配接口 |
| 多 Agent 路由冲突 | 中 | 消息路由到错误 Agent | 路由优先级明确 + 路由决策日志 + 集成测试覆盖 |
| 控制面暴露风险 | 低 | 管理接口被滥用 | 默认 127.0.0.1 + Token + 审计日志 + 受限默认配置 |
