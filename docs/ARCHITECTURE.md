# ISAC — 生产级架构设计文档

> Intelligent Social AI Companion v3.0
> 状态: 生产级目标设计
> v3.0: 多 Agent 架构 (多实例 / 共享 Channel + 路由 / Agent 互联 / 控制面)

---

## 目录

- [一、设计原则](#一设计原则)
- [二、系统架构](#二系统架构)
- [三、核心组件设计](#三核心组件设计)
- [四、配置版本化](#四配置版本化)
- [五、消息生命周期](#五消息生命周期)
- [六、目录结构](#六目录结构)
- [七、设计决策记录](#七设计决策记录)
- [八、非功能性需求](#八非功能性需求)

---

## 一、设计原则

| 原则 | 说明 |
|------|------|
| **拟人表达靠 Prompt，拟人行为靠 Runtime** | 人格、语气、情绪、记忆通过 System Prompt 注入；回复节奏、等待、主动、打断、上下文恢复由 ConversationRuntime 等运行机制实现 |
| **单点集成** | 所有子系统通过 `SystemPromptBuilder` 和 `AgentHooks` 两个枢纽参与 Agent 循环 |
| **门控先于 Agent** | 是否回复、何时回复的决定先于 Agent 调用 |
| **记忆是检索流水线** | 嵌入模型 + 双路径搜索 + 重排序，不是简单 K-V |
| **事件驱动** | 消息处理通过 EventBus 双层事件 (Intercept + Async) 解耦 |
| **多 Agent 原生** | 单进程运行多个 Agent 实例，配置/记忆/人格/工具各自隔离 |
| **连接与路由分离** | Channel 连接是共享资源，由 Router 决定消息归属哪个 Agent |
| **Agent 互联显式化** | Agent 间通信通过 InterAgentBus + 显式 Link (ACL)，默认不互通 |
| **控制面/数据面分离** | 消息处理 (数据面) 与管理自动化 (Admin API / MCP Server 控制面) 解耦 |
| **兼容 AstrBot / MaiBot** | 不发明新插件协议，桥接 AstrBot Star 与 MaiBot 插件系统 |
| **原生 SDK 面向扩展** | ISAC Native SDK 承载兼容层无法覆盖的独有能力 |
| **简洁优先** | 不引入不必要的外部依赖，单机可运行 |

---

## 二、系统架构

专项施工图：

| 文档 | 内容 |
|------|------|
| [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md) | ConversationRuntime、wait、主动任务、打断、上下文恢复、表达/黑话/行为学习 |
| [MEMORY_DESIGN.md](./MEMORY_DESIGN.md) | 记忆分层、身份归一、写入/检索/注入/治理、无 embedding 模式 |
| [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md) | primary/observer/candidate Agent、旁听、handoff、Agent Mesh ACL |
| [PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md) | AstrBot / MaiBot / Native 插件兼容范围、权限、生命周期与测试 |
| [CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md) | REST API、MCP Server、Webhook、认证、审计、自动化安全默认值 |

```
┌───────────────────────────────────────────────────────────────────────────┐
│                      ISAC System Architecture (v3.0)                       │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   ┌────────────────────── CONTROL PLANE (控制面) ───────────────────┐    │
│   │  WebUI v2 │ Admin REST API │ MCP Server │ Webhooks / Automation │    │
│   │  管理 Agent/路由/模型/用量/扩展/记忆/任务 (Token + Scope)       │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │ (管理操作复用各层公开方法，商业化预留)    │
│   ┌────────────────────── CHANNEL LAYER ────────────────────────────┐    │
│   │                                                                 │    │
│   │   QQ  Telegram  Discord  WeChat  Slack  KOOK  WebSocket ...   │    │
│   │          AstrBot Platform Adapters (18+)                       │    │
│   │   连接是共享资源: 一个 IM 连接可服务多个 Agent                  │    │
│   │                   统一消息模型: ISACMessage                     │    │
│   │                                                                 │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌────────────────────── GATEWAY ────────────────────────────────┐    │
│   │                                                               │    │
│   │  ┌──────────────┐  ┌──────────────────┐  ┌───────────────┐  │    │
│   │  │  EventBus    │  │  SessionManager  │  │  UserMapper   │  │    │
│   │  │ (Intercept   │  │  (SQLite 持久化)  │  │ (跨平台用户)   │  │    │
│   │  │  + Async)    │  │                  │  │               │  │    │
│   │  └──────────────┘  └──────────────────┘  └───────────────┘  │    │
│   │                                                               │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌────────────────── MESSAGE ROUTER (路由) ──────────────────────┐    │
│   │  决定消息归属哪个 Agent:                                      │    │
│   │  1. 显式绑定 (platform + group/user → agent_id)               │    │
│   │  2. 触发词匹配 (AgentConfig.trigger_words, 匹配后剥离)         │    │
│   │  3. Channel 默认 Agent (default_agent_id, 无需触发词)          │    │
│   │  4. 无匹配 → DROP                                             │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │ (agent_id + 剥离触发词后的消息)           │
│   ┌═══════════════ AGENT RUNTIME (多 Agent 实例) ═══════════════┐    │
│   │  AgentManager: 创建/启动/停止/销毁, 按 AgentConfig 独立组装  │    │
│   │  以下各层在每个 AgentInstance 内独立实例化, 互不共享可变状态 │    │
│   │                                                              │    │
│   │  ┌─────────────────── GATING SYSTEM (门控) ────────────────┐ │    │
│   │                                                               │    │
│   │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │    │
│   │  │ReplyNecessity│  │TurnScheduler │  │  IdleBackoff      │  │    │
│   │  │  Judge       │  │              │  │                   │  │    │
│   │  └──────────────┘  └──────────────┘  └───────────────────┘  │    │
│   │                                                               │    │
│   │  决定: 是否进入 Agent Loop、何时进入、频率控制              │    │
│   │  输入: pending_count, has_at, is_private, idle_seconds...   │    │
│   │  输出: TRIGGER / WAIT / DELAY(N秒)                          │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌─────────────── SYSTEM PROMPT BUILDER ────────────────────────┐    │
│   │                                                               │    │
│   │  System Prompt 组装器 —— 所有子系统的集成枢纽                 │    │
│   │                                                               │    │
│   │  Injector 注册表:                                             │    │
│   │  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │    │
│   │  │base_identity │  │personality   │  │attention_drift    │  │    │
│   │  │              │  │_rules        │  │                   │  │    │
│   │  ├──────────────┤  ├──────────────┤  ├───────────────────┤  │    │
│   │  │expression    │  │mood_system   │  │heuristic_memory   │  │    │
│   │  │_style        │  │              │  │ (低频)            │  │    │
│   │  ├──────────────┤  ├──────────────┤  ├───────────────────┤  │    │
│   │  │person_profile│  │jargon        │  │mid_term_memory    │  │    │
│   │  │              │  │              │  │ (低频)            │  │    │
│   │  ├──────────────┤  ├──────────────┤  ├───────────────────┤  │    │
│   │  │skill_selector│  │tools_available│  │context_summary   │  │    │
│   │  └──────────────┘  └──────────────┘  └───────────────────┘  │    │
│   │                                                               │    │
│   │  每个 Injector 独立实现，带频率控制                            │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌──────────────── ISAC AGENT LOOP ────────────────────────────┐    │
│   │                                                               │    │
│   │  class ISACAgentLoop:                                        │    │
│   │      while budget.remaining:                             │    │
│   │          hook: pre_llm → LLM.chat → hook: post_llm          │    │
│   │          if tool_calls:                                      │    │
│   │              hook: pre_tool → exec_tool → hook: post_tool    │    │
│   │          else:                                               │    │
│   │              hook: final_response → return                  │    │
│   │                                                               │    │
│   │  子系统通过 Hooks 参与 Agent 循环:                          │    │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │    │
│   │  │Memory    │ │Persona   │ │Skill     │ │Plugin    │      │    │
│   │  │(检索/更新)│ │(风格注入)│ │(技能选择)│ │(插件钩子)│      │    │
│   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌────────────────── MEMORY SYSTEM (记忆系统) ─────────────────┐    │
│   │                                                               │    │
│   │  检索流水线:                                                  │    │
│   │  Query → [Embed] → Dense Search ──→┐                        │    │
│   │                    Sparse (BM25) ──┼→ [RRF Fusion]          │    │
│   │                                     ↓                        │    │
│   │                              [Reranker] → Top-K             │    │
│   │                                     ↓                        │    │
│   │                              Format → Inject                 │    │
│   │                                                               │    │
│   │  触发策略:                                                    │    │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │    │
│   │  │Heuristic │ │Mid-term  │ │Person    │ │Jargon    │      │    │
│   │  │Memory    │ │Memory    │ │Profile   │ │Match     │      │    │
│   │  │(3min冷却)│ │(上下文压缩)│ │(每轮)   │ │(每轮)   │      │    │
│   │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │    │
│   │                                                               │    │
│   │  存储引擎:                                                    │    │
│   │  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │    │
│   │  │VectorStore│ │Metadata  │ │GraphStore│                     │    │
│   │  │(sqlite-vec)│ │Store     │ │(关系图)  │                     │    │
│   │  └──────────┘ └──────────┘ └──────────┘                     │    │
│   │  └───────────────────────────┬───────────────────────────────┘ │    │
│   │                              │                                 │    │
│   │  ┌──────────────── INTER-AGENT BUS (Agent 互联) ────────────┐ │    │
│   │  │  显式 Link (ACL, 默认不互通): ask_agent / notify / handoff │ │    │
│   │  └──────────────────────────────────────────────────────────┘ │    │
│   └═══════════════════════════╪══════════════════════════════════╝    │
│                               │                                          │
│   ┌────────────────── PLUGIN SYSTEM ────────────────────────────┐    │
│   │                                                               │    │
│   │  ┌───────────────────────────────────────────────────────┐  │    │
│   │  │  AstrBot Compatibility Layer                          │  │    │
│   │  │  Star / Context / EventType / FunctionTool            │  │    │
│   │  └───────────────────────────────────────────────────────┘  │    │
│   │  ┌───────────────────────────────────────────────────────┐  │    │
│   │  │  MaiBot Compatibility Layer                           │  │    │
│   │  │  Plugin / Action / Command 映射                       │  │    │
│   │  └───────────────────────────────────────────────────────┘  │    │
│   │  ┌───────────────────────────────────────────────────────┐  │    │
│   │  │  ISAC Native SDK v2 (专用拓展系统)                     │  │    │
│   │  │  Hooks / Injectors / Tools / Commands /               │  │    │
│   │  │  InterAgent Hooks / Admin Routes (预留) / MCP         │  │    │
│   │  └───────────────────────────────────────────────────────┘  │    │
│   │  启用矩阵: Agent × Plugin, Channel × Plugin 独立配置      │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌────────────────── PROVIDER LAYER ───────────────────────────┐    │
│   │                                                               │    │
│   │  LLM / Embedding / Reranker / STT / TTS / ImageGen / Video │    │
│   │  ProviderManager: 共享池, 可按 Agent 配置独立实例            │    │
│   │  UsageRecorder: 每次物理请求按 Provider/模型/Agent/模态计量  │    │
│   │  来源: AstrBot (42 providers) + opencode LLM                │    │
│   │                                                               │    │
│   └───────────────────────────────────────────────────────────┘    │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心组件设计

### 3.1 Agent Runtime — 多 Agent 实例管理

**核心职责**: 在单进程内运行多个相互隔离的 Agent 实例。

```python
@dataclass
class AgentInstance:
    """一个运行中的 Agent。所有子系统按实例独立组装，不共享可变状态。"""
    agent_id: str
    config: AgentConfig                 # 独立配置 (人格/门控/记忆/工具/插件/MCP/命令)
    gating: GatingSystem
    prompt_builder: SystemPromptBuilder
    hooks: AgentHooks
    loop: ISACAgentLoop
    memory: MemoryRetrievalPipeline     # 绑定 agent_id 记忆命名空间
    persona: PersonaManager
    status: str = "stopped"             # "running" | "stopped" | "error"


class AgentManager:
    """Agent 生命周期管理。所有公开方法同时暴露给控制面 (Admin API / MCP)。"""

    async def create(self, config: AgentConfig) -> AgentInstance: ...
    async def start(self, agent_id: str) -> None: ...
    async def stop(self, agent_id: str) -> None: ...
    async def destroy(self, agent_id: str, *, keep_memory: bool = True) -> None: ...
    async def get(self, agent_id: str) -> AgentInstance | None: ...
    async def list(self) -> list[AgentInstance]: ...
    async def reload_config(self, agent_id: str, config: AgentConfig) -> None: ...
```

**设计要点**:
- 每个 AgentInstance 的 Gating / PromptBuilder / Hooks / Memory / Persona 独立实例化
- Provider 由 ProviderManager 池化共享；AgentConfig.llm 非空时为该 Agent 创建独立实例
- 所有 Provider 调用通过 `UsageRecorder` 记录 `ModelUsageEvent`；重试与回退按物理请求分别计量，最终聚合时用 `trace_id` 归并
- 原始用量与成本分离：Provider 只标准化实际 usage，`PricingCatalog` 按调用时价格版本计算估算成本；价格未知不阻断调用
- `ModelCatalog` 维护文本、视觉、语音、图片、视频、Embedding、Reranker 的能力声明；`ModelRouter` 按 operation、输入/输出模态、Agent 授权、健康状态、成本和延迟选择实现
- Agent 只看到语义能力工具，不感知具体厂商模型；生成媒体统一写入 `ArtifactStore`，由 Channel Adapter 按平台能力发送或降级为受控链接
- 配置来源: `data/agents/<agent_id>/config.jsonc`（只写相对全局配置的覆盖项）
- 注册表持久化: `data/agents/registry.jsonc`，重启后自动恢复 running 状态的 Agent
- 向后兼容: 无 `data/agents/` 时自动创建默认 Agent，行为同单 Agent 模式

---

### 3.2 Message Router — 消息路由

**核心职责**: Channel 连接与 Agent 解耦的关键——决定每条消息归属哪个 Agent。

```python
@dataclass
class RoutingDecision:
    agent_id: str
    matched_by: str                     # "binding" | "trigger_word" | "default"
    content: str                        # 剥离触发词后的内容


class MessageRouter:
    """消息路由器。规则可热更新 (控制面写入 data/routing.jsonc)。"""

    async def route(self, message: ISACMessage) -> RoutingDecision | None:
        """
        优先级 (先匹配先生效):
        1. 显式绑定: (platform, group_id/user_id) → agent_id
        2. 触发词: 消息以某 Agent 的 trigger_word 开头 (专用/特定触发词)
        3. 默认 Agent: 该 platform 配置 default_agent_id (无需任何触发词)
        4. 无匹配 → None (DROP + 记录日志)
        """

    def set_rules(self, rules: RoutingRules) -> None: ...
    def get_rules(self) -> RoutingRules: ...
```

**设计要点**:
- 触发词命中后从消息内容中剥离，再进入目标 Agent 的 Gating
- 一个 IM 连接可服务多个 Agent（绑定 + 触发词 + 默认 Agent 决定归属）
- 一个 Agent 可同时绑定多个 IM（多 platform 的规则指向同一 agent_id）
- **预留接口**: Native SDK `register_router_hook(fn)` 注册自定义路由函数（如按自动化流程分配），在优先级 1 之前执行

---

### 3.3 Inter-Agent Bus — Agent 互联

**核心职责**: Agent 间通信总线。默认不互通，必须显式配置 Link (ACL)。

详细的 primary / observer / candidate Agent、旁听、handoff 与 Agent Mesh ACL 见 [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md)。

```python
@dataclass
class InterAgentLink:
    from_agent: str
    to_agent: str
    direction: str = "both"             # "both" | "oneway"
    enabled: bool = True


@dataclass
class InterAgentMessage:
    from_agent: str
    to_agent: str
    type: str                           # "request" | "response" | "notify" | "handoff"
    content: str
    context: dict = field(default_factory=dict)  # 会话摘要等附带信息


class InterAgentBus:
    """Agent 间通信总线。所有互联消息经过总线，天然是审计/拦截点。"""

    async def send(self, message: InterAgentMessage) -> InterAgentMessage | None:
        """检查 Link ACL → 投递到目标 Agent (经其 Gating/AgentLoop) → 返回响应"""

    def add_link(self, link: InterAgentLink) -> None: ...
    def remove_link(self, from_agent: str, to_agent: str) -> None: ...
    def can_talk(self, from_agent: str, to_agent: str) -> bool: ...
    def list_links(self) -> list[InterAgentLink]: ...
```

**设计要点**:
- Agent 通过内置工具 `ask_agent(target_agent, question)` 发起通信
- `handoff` 类型用于会话移交（Agent A 把当前对话连同摘要转给 Agent B）
- 接收方将互联消息作为特殊消息进入自己的 Agent Loop，System Prompt 标注来源 Agent
- Link 配置持久化: `data/links.jsonc`，控制面可热更新
- Native SDK 可注册 `on_inter_agent_message` 钩子参与互联流程

---

### 3.4 System Prompt Builder — 所有子系统的集成枢纽

**核心职责**: 把各子系统的 Prompt 注入块组装成最终的 System Prompt。

**设计要点**:
- 每个注入器独立实现 `PromptInjector` 协议
- 注入器自带频率控制（不需要每次调用）
- 注入器自带 token 预算估算
- 注入顺序按 priority 排序，可预算裁剪

**接口定义**:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

# ── Context 层次定义 ──────────────────────────────────────

@dataclass
class RuntimeContext:
    """贯穿一次消息处理的全局上下文（所有子 Context 的基类）"""
    session: Session
    user_profile: UserProfile | None
    current_message: ISACMessage
    pending_messages: list[ISACMessage] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class InjectionContext(RuntimeContext):
    """PromptInjector 上下文"""
    available_prompt_tokens: int = 8000


@dataclass
class AgentContext(RuntimeContext):
    """Agent Loop 运行时上下文"""
    budget: Budget = field(default_factory=lambda: Budget())
    iteration: int = 0
    interrupt_requested: bool = False
    reasoning_content: str = ""
    available_prompt_tokens: int = 8000
    streaming: bool = False                              # 是否以流式模式调用 LLM
    on_chunk: Callable[[LLMChunk], Awaitable[None]] | None = None  # 流式回调


@dataclass
class GatingContext(RuntimeContext):
    """门控决策上下文"""
    pending_count: int = 0
    has_at: bool = False          # 消息中是否 @ Bot（由消息平台元数据/segment 判定）
    has_mention: bool = False     # 消息文本是否提及 Bot 名字（不含 @）；由 AgentManager 按 Agent display_name 填充
    is_private: bool = False
    idle_seconds: float = 0.0
    effective_frequency: float = 1.0
    recent_self_replies: int = 0
    recent_window_messages: int = 0
    focus_active: bool = False  # Focus Mode 是否激活


class PromptInjector(ABC):
    """Prompt 注入器抽象基类。所有注入器必须继承此类。

    位置: `isac/core/injector.py`。
    放在 core 而非 agent，是为了让 `memory/injector/` 与 `agent/injectors/`
    都能单向依赖 core，避免 memory → agent 的导入环。
    """

    @property
    def key(self) -> str:
        """注入器唯一标识"""
        raise NotImplementedError

    @property
    def priority(self) -> int:
        """注入优先级 (数字越大越先注入)"""
        return 50

    @property
    def max_frequency_seconds(self) -> float:
        """最小触发间隔 (秒)。0 = 每次"""
        return 0.0

    @property
    def max_new_messages(self) -> int:
        """最小新消息数。0 = 不限制"""
        return 0

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return True

    @property
    def tokens_estimate(self) -> int:
        """预估 token 数 (用于预算管理)"""
        return 200

    @abstractmethod
    async def build(self, context: InjectionContext) -> str:
        """返回注入文本，空字符串表示不注入"""
        ...


class SystemPromptBuilder:
    """System Prompt 组装器"""

    def register(self, injector: PromptInjector) -> None: ...

    async def build(self, context: InjectionContext) -> str: ...
```

---

### 3.5 Agent Loop — 开放注入点

**核心职责**: 执行 LLM 对话循环，通过 hooks 让各子系统参与。

**Hooks 定义**:

```python
from enum import Enum
from typing import Callable

class AgentHookPoint(Enum):
    PRE_LLM = "pre_llm"           # LLM 调用前，可修改 messages
    POST_LLM = "post_llm"         # LLM 响应后，可处理 response
    PRE_TOOL = "pre_tool"         # 工具调用前，返回 False 可阻止
    POST_TOOL = "post_tool"       # 工具调用后，可触发副作用
    COMPRESS = "compress"         # 上下文过大时触发
    FINAL_RESPONSE = "final_response"  # 最终回复前


class AgentHooks:
    """钩子注册表"""

    def register(self, point: AgentHookPoint, fn: Callable, priority: int = 0): ...
    async def fire(self, point: AgentHookPoint, *args, **kwargs): ...
```

**Agent Loop 主流程**:

```python
class ISACAgentLoop:
    async def run(self, messages: list[Message], context: AgentContext) -> AgentResult:
        iteration = 0

        while context.budget.remaining:
            iteration += 1
            context.iteration = iteration

            # 每轮重新构建 system prompt（记忆/画像/行话需要刷新）
            system_prompt = await self.prompt_builder.build(context)

            # PRE_LLM: 记忆检索/画像/行话 等在这里注入
            messages = await self.hooks.fire(AgentHookPoint.PRE_LLM, messages, context)

            # LLM 调用（支持流式和非流式）
            response = await self._call_llm(system_prompt, messages, tools, context)

            # 被新消息打断
            if context.interrupt_requested:
                return AgentResult(interrupted=True)

            if response.tool_calls:
                for tc in response.tool_calls:
                    # PRE_TOOL: 权限检查
                    allowed = await self.hooks.fire(AgentHookPoint.PRE_TOOL, tc, context)
                    if not allowed:
                        continue

                    # 工具执行（带错误处理）
                    try:
                        result = await self.tools.execute(tc, context)
                    except ToolError as exc:
                        logger.warning("工具执行失败", tool=tc.name, error=str(exc))
                        result = ToolResult(
                            content=f"工具 {tc.name} 执行失败: {exc.message}",
                            is_error=True,
                        )
                    except Exception as exc:
                        logger.error("工具执行严重错误", tool=tc.name, error=str(exc), exc_info=True)
                        result = ToolResult(content="工具执行内部错误", is_error=True)

                    # POST_TOOL: 触发记忆更新等内部副作用
                    await self.hooks.fire(AgentHookPoint.POST_TOOL, tc, result, context)

                    # 结构化进度事件交给 ProgressReporter；发送失败不影响主循环
                    await context.report_progress(
                        ProgressEvent.from_tool_result(tc, result, context)
                    )
                    messages.append(ToolResultMessage(tc.id, result))
            else:
                await self.hooks.fire(AgentHookPoint.FINAL_RESPONSE, response, context)
                return AgentResult(content=response.content)

            # COMPRESS: 上下文过大时
            if context.should_compress():
                await self.hooks.fire(AgentHookPoint.COMPRESS, messages, context)

        return AgentResult(stopped_by_budget=True)

    async def _call_llm(self, system_prompt, messages, tools, context):
        """统一 LLM 调用入口，处理流式和非流式"""
        if context.streaming:
            # 流式: 边流边收集，结束后合并
            chunks: list[LLMChunk] = []
            async for chunk in self.llm.chat_stream(system_prompt, messages, tools):
                chunks.append(chunk)
                # 可选: 实时推送给用户
                if context.on_chunk:
                    await context.on_chunk(chunk)
            return self._merge_chunks(chunks)
        else:
            return await self.llm.chat(system_prompt, messages, tools)

    def _merge_chunks(self, chunks: list[LLMChunk]) -> LLMResponse:
        """将流式 chunks 合并为完整响应"""
        content = "".join(c.delta_content for c in chunks)
        reasoning = "".join(c.delta_reasoning for c in chunks)
        tool_calls = [c.tool_call for c in chunks if c.tool_call]
        usage = TokenUsage(
            input_tokens=chunks[-1].usage.input_tokens if chunks else 0,
            output_tokens=chunks[-1].usage.output_tokens if chunks else 0,
        )
        return LLMResponse(
            content=content,
            reasoning=reasoning,
            tool_calls=tool_calls,
            usage=usage,
        )
```

**各子系统注册的 Hooks**:

| Hook | 注册子系统 | 作用 |
|------|-----------|------|
| `PRE_LLM` | HeuristicMemoryInjector | 低频记忆检索注入 |
| `PRE_LLM` | PersonProfileInjector | 人物画像注入 |
| `PRE_LLM` | JargonInjector | 行话匹配注入 |
| `POST_TOOL` | MemoryEncoder | 工具调用后更新记忆 |
| `POST_TOOL` | TurnScheduler | 更新话轮频率 |
| `ProgressEvent` | ProgressReporter | 对工具阶段做频控、脱敏、人格化渲染并经原 Channel 汇报 |
| `COMPRESS` | MidTermMemoryManager | 触发中期记忆压缩 |
| `FINAL_RESPONSE` | TurnScheduler | 记录本轮回复 |
| `FINAL_RESPONSE` | BehaviorLearner | 从回复中学习行为模式 |

---

### 3.6 Memory System — 检索流水线

**核心职责**: 跨会话的记忆存储、检索、注入。

记忆分层、身份归一、写入流水线、无 embedding 模式、治理与 Schema 补充见 [MEMORY_DESIGN.md](./MEMORY_DESIGN.md)。

**架构**:

```
┌──────────────────────────────────────────────────────────┐
│                    Memory Pipeline                        │
│                                                          │
│   触发策略                                                │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│   │Heuristic │ │Mid-term  │ │Person    │ │Jargon    │  │
│   │(3min冷却)│ │(上下文压缩)│ │Profile  │ │Match     │  │
│   │          │ │          │ │(每轮)    │ │(每轮)    │  │
│   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │
│        └─────────────┴────────────┴────────────┘        │
│                        │                                │
│                   Query Builder                          │
│                        │                                │
│                   Embedding (text → vector)              │
│                        │                                │
│        ┌───────────────┼───────────────┐                 │
│        ▼               ▼               ▼                 │
│   Dense Search    Sparse Search    Graph Search          │
│   (VectorStore)   (BM25)           (关系图)              │
│        │               │               │                 │
│        └───────────────┼───────────────┘                 │
│                        ▼                                │
│                   RRF Fusion (RRF)                       │
│                        │                                │
│                   Reranker (可选)                         │
│                        │                                │
│                   Top-K Results                          │
│                        │                                │
│                   Format Injection                       │
│                        │                                │
│                   → System Prompt Builder                │
│                                                          │
│   存储引擎:                                               │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│   │VectorStore│ │Metadata  │ │GraphStore│               │
│   │(sqlite-vec)│ │Store     │ │(关系图)  │               │
│   │          │ │(SQLite+  │ │          │               │
│   │          │ │  FTS5)   │ │          │               │
│   └──────────┘ └──────────┘ └──────────┘               │
└──────────────────────────────────────────────────────────┘
```

**存储层 Schema**:

```sql
-- MetadataStore (SQLite)

CREATE TABLE episodes (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,     -- 记忆命名空间 ("shared" = 跨 Agent 共享)
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    topics TEXT,            -- JSON array
    participants TEXT,      -- JSON array
    emotion TEXT,
    importance REAL DEFAULT 0.5,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX idx_episodes_agent ON episodes(agent_id);
CREATE INDEX idx_episodes_user ON episodes(user_id);
CREATE INDEX idx_episodes_time ON episodes(created_at);

CREATE VIRTUAL TABLE episodes_fts USING fts5(
    content, summary, topics, participants,
    content=episodes, content_rowid=rowid
);

CREATE TABLE person_profiles (
    agent_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    name TEXT NOT NULL,
    profile_text TEXT,
    traits TEXT,            -- JSON array
    relationship_depth REAL DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    first_seen INTEGER,
    last_seen INTEGER,
    embedding_hash TEXT,    -- 用于向量关联
    PRIMARY KEY (agent_id, person_id)
);

CREATE TABLE jargon_entries (
    agent_id TEXT NOT NULL,
    word TEXT NOT NULL,
    meaning TEXT NOT NULL,
    context TEXT,
    usage_count INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (agent_id, word)
);

-- VectorStore (sqlite-vec)

CREATE VIRTUAL TABLE vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[1024]    -- 维度可配置
);
-- 注: vectors 通过 id 关联 MetadataStore，按 agent_id 过滤在查询层完成
```

**嵌入模型管理**:

```python
class EmbeddingManager:
    """
    嵌入模型管理器。
    支持本地模型 (fastembed/sentence-transformers) 和 API 调用。
    带降级: 如果模型不可用，自动降级到稀疏搜索。
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化"""

    async def embed_query(self, query: str) -> list[float]:
        """查询向量化"""

    def get_fingerprint(self) -> dict:
        """返回模型指纹，用于向量一致性检查"""

    def is_degraded(self) -> bool:
        """是否处于降级状态 (模型不可用)"""
```

**重排序管理**:

```python
class Reranker:
    """
    重排序管理器。
    支持本地模型 (bge-reranker) 和 API (Cohere/Jina)。
    """

    async def rerank(self, query: str, candidates: list[MemoryHit]) -> list[MemoryHit]:
        """对候选结果重排序"""

    def is_available(self) -> bool:
        """重排序模型是否可用"""
```

---

### 3.7 Gating System — 门控

**核心职责**: 决定"要不要说话、什么时候说"。

Gating 是拟人化行为层的一部分；会话级消息缓存、静默窗口、wait、主动任务、Planner 打断与上下文恢复见 [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md)。

```
Message In
    │
    ▼
[Gating System]
    │
    ├── 是私聊且 @bot → 直接 TRIGGER
    │
    ├── 计算 Reply Necessity Score
    │   基础分: has_at(100) | has_mention(80) | private(40) | focus(40) | 普通(0)
    │   + 内容分: 问题+15, 请求+20, 征询+20, 长文本+5~10, 短反应-25
    │   + 压力分: pending 消息积压 (0~100)
    │   - 存在感惩罚: 近5分钟发言占比 (0~-25)
    │   × 频率系数 (0.5~1.0)
    │   阈值: 80 分
    │
    ├── 检查 Idle Backoff
    │   连续空闲 → 指数退避 (2^n 秒)
    │
    └── 输出: TRIGGER / WAIT / DELAY(N秒)
```

**实现**:

```python
class GatingSystem:
    def __init__(self):
        self.reply_necessity = ReplyNecessityJudge()
        self.turn_scheduler = TurnScheduler()
        self.idle_backoff = IdleBackoffController()
        self.focus_mode = FocusMode()  # Focus Mode 管理

    async def evaluate(self, pending: list[Message], context: GatingContext) -> GateDecision:
        """
        返回 TRIGGER / WAIT / DELAY(seconds)
        """

        # 1. Focus Mode 激活时直接 TRIGGER (群聊中的积极参与)
        if self.focus_mode.is_active(context.session.session_id):
            return GateDecision.TRIGGER

        # 2. 强制触发
        if context.has_at or (context.is_private and context.has_mention):
            return GateDecision.TRIGGER

        # 3. 回复必要性评分
        score = self.reply_necessity.score(pending, context)
        if score < self.threshold:
            return GateDecision.WAIT

        # 4. 空闲退避
        if self.idle_backoff.should_delay(context.pending_count):
            return GateDecision.delay(self.idle_backoff.remaining_seconds)

        return GateDecision.TRIGGER


class FocusMode:
    """专注模式管理 (来自 MaiBot)

    当 bot 在某群聊处于 focus 状态时:
    - Reply Necessity 基础分提升 (普通消息也 +40 分)
    - Idle Backoff 被绕过
    - Turn Scheduler 阈值降低

    触发方式:
    - 用户通过命令 (如 /focus) 主动开启
    - 系统检测到高互动时自动开启
    - 有时间限制，超时自动退出
    """

    def is_active(self, session_id: str) -> bool: ...
    def enter(self, session_id: str, duration: int = 300): ...
    def exit(self, session_id: str): ...
```

---

### 3.8 Plugin System — AstrBot / MaiBot 兼容 + 原生 SDK

插件格式识别、兼容范围矩阵、权限模型、生命周期和兼容测试见 [PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md)。

**兼容层架构**:

```
┌────────────────────────────────────────────────────────┐
│              AstrBot Plugin (用户已有插件)              │
│                     不改代码直接运行                     │
└─────────────────────────┬──────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
   ┌──────────────────┐   ┌──────────────────────┐
   │  EventType 映射   │   │  Context API 模拟    │
   │                  │   │                      │
   │  OnMessageEvent →│   │  context.send_message│
   │  ON_MESSAGE      │   │  → ISAC.send()      │
   │                  │   │                      │
   │  OnLLMRequest   →│   │  context.get_provider│
   │  PRE_LLM        │   │  → ISAC Provider     │
   │                  │   │                      │
   │  ...             │   │  ...                 │
   └──────────────────┘   └──────────────────────┘
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
   ┌──────────────────┐   ┌──────────────────────┐
   │  FunctionTool 桥接│   │  Plugin 沙箱          │
   │                  │   │                      │
   │  AstrBot Tool →  │   │  拦截 astrbot.core  │
   │  ISAC Tool       │   │  import 重定向       │
   └──────────────────┘   └──────────────────────┘
```

**兼容策略** (按优先级):
- P0: EventType 映射 + FunctionTool 桥接 → 覆盖 **80%** 插件
- P1: Context API 模拟 (send_message, get_provider, get_platform) → 覆盖 **15%**
- P2: 内部模块重定向 (astrbot.core import 拦截) → 覆盖 **5%**

**P2 沙箱实现说明**:

```python
# 方案: sys.meta_path 自定义查找器
# 拦截 astrbot.* 的 import，重定向到 ISAC 兼容层
# 使用 Python 3.12 兼容的 find_spec / exec_module 协议

import importlib
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec


class AstrBotImportFinder(MetaPathFinder):
    """拦截 astrbot.* 的 import"""

    # 兼容层覆盖的 astrbot 模块清单
    MAPPING = {
        "astrbot.api.star": "isac.plugin.compatibility.astrbot.star",
        "astrbot.api.event": "isac.plugin.compatibility.astrbot.events",
        "astrbot.api.provider": "isac.plugin.compatibility.astrbot.context",
        "astrbot.api.platform": "isac.plugin.compatibility.astrbot.context",
    }

    def find_spec(self, name: str, path=None, target=None):
        if not name.startswith("astrbot."):
            return None
        if name in self.MAPPING:
            target_module = self.MAPPING[name]
            importlib.import_module(target_module)  # 预加载目标模块
            return ModuleSpec(name, AstrBotModuleLoader(target_module), origin=target_module)
        raise ImportError(
            f"不支持的 astrbot 模块: {name}。"
            f"兼容层仅覆盖: {list(self.MAPPING.keys())}"
        )


class AstrBotModuleLoader(Loader):
    def __init__(self, target_module: str):
        self.target = target_module

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        target = importlib.import_module(self.target)
        sys.modules[module.__name__] = target


# 安装沙箱 (在插件加载前)
sys.meta_path.insert(0, AstrBotImportFinder())
```

**局限性**: 深层 import (如 `from astrbot.core.xxx import yyy`) 需要为每个子模块建立映射。建议 P2 阶段先实现常用模块的映射，其他按需扩展。

**MaiBot 兼容层**:

与 AstrBot 兼容层同构，将 MaiBot 插件能力映射到 ISAC：

| MaiBot 概念 | ISAC 映射 |
|-------------|-----------|
| Plugin 基类 | `ISACPlugin` 包装 (`plugin/compatibility/maibot/plugin.py`) |
| Action (动作) | Agent Tool / AgentHooks |
| Command (命令) | ISAC Command (`commands/`) |
| 事件处理器 | EventBus / AgentHooks |
| 插件配置 | Plugin Manifest `config_schema` |

- 加载器自动识别 `plugins/` 下的 AstrBot / MaiBot / ISAC 原生三种格式
- **锁定兼容的 MaiBot 版本**，API 细节以锁定版本为准，版本变动只改适配器
- 与 AstrBot 兼容层共用沙箱与权限体系

**ISAC Native SDK v2 (专用拓展系统)**:

超越兼容层的能力，面向更强的扩展：

- Hooks / Injectors / Tools（与兼容层相同的基础能力）
- **Commands** — 用户斜杠命令，可按 Agent / Channel 独立启停
- **Inter-Agent Hooks** — `on_inter_agent_message` 等互联钩子
- **Admin Routes**（预留）— 插件向 Admin API 注册管理端点
- **自定义扩展点**（预留）— Memory Backend / Provider / Router Hook

**插件启用矩阵**:

插件可用性按两级矩阵控制，配置即可生效，无需改代码：

- Agent 级: `AgentConfig.plugins_allow / plugins_deny`
- Channel 级: 全局配置 `plugins.channel_matrix`
- 有效权限 = Agent 允许 ∩ Channel 允许 ∩ 工具权限策略（DEVELOP.md 7.3）

---

### 3.9 Control Plane — 管理自动化 (商业化预留)

**核心职责**: 独立于数据面的管理面。不参与消息处理，只管理配置与生命周期，所有操作复用 AgentManager / Router / Bus / PluginManager 的公开方法。

资源模型、REST API、MCP Server、Webhook、认证、审计与自动化安全默认值见 [CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md)。

```
┌────────────────────────────────────────────────────────────┐
│  Admin REST API (FastAPI, 默认 127.0.0.1 + Token 认证)      │
│  - Agent CRUD / 启停 / 配置读写                             │
│  - Channel 绑定 / 路由规则 / 默认 Agent                     │
│  - Inter-Agent Link 管理                                    │
│  - 插件启用矩阵 / MCP Server 配置                           │
├────────────────────────────────────────────────────────────┤
│  ISAC MCP Server (ISAC 作为 MCP 服务端)                     │
│  - 暴露管理工具: agent_create / agent_bind /                │
│    route_set_default / link_create / config_set ...         │
│  - 外部系统可用任意 MCP 客户端自动化管理 ISAC               │
├────────────────────────────────────────────────────────────┤
│  Webhooks / Automation                                      │
│  - 事件推送: message.received / agent.created / ...         │
│  - 自动化触发器: 外部事件 → 创建 Agent → 绑定 IM            │
│  - 预留: 自定义 Workflow 编排接口                           │
└────────────────────────────────────────────────────────────┘
```

**设计要点**:
- 自动化示例: Webhook 收到事件 → `POST /agents` 创建 Agent → `POST /channels/{platform}/agents/{id}` 绑定 → 设置默认 Agent
- 认证: `Authorization: Bearer <api_token>`，默认仅监听 127.0.0.1
- 通过自动化创建的 Agent 使用受限默认配置（deny-by-default 工具策略）
- WebUI 只作为 Control API 客户端，不直读配置文件或运行时对象；配置修改经过 Schema 校验 → diff → 确认 → `If-Match` 乐观并发 → 审计
- Provider 密钥只可替换不可回显，管理 Token 不写入浏览器 localStorage；实时状态通过按 scope 过滤、可断线恢复的 SSE/WebSocket 提供
- WebUI v2 信息架构、配置编辑事务、实时事件与可访问性要求见 `CONTROL_PLANE_SPEC.md` 第八章
- 详细端点与 MCP 工具清单见 SPECIFICATION.md 4.4 / 4.5

---

## 四、配置版本化

### 4.1 配置版本管理

配置文件带版本号，升级时自动迁移旧配置（参考 MaiBot 的 `config_upgrade_hooks.py`）：

```jsonc
{
    "config_version": "1.0.0",  // 配置版本号
    "debug": false,
    ...
}
```

```python
class ConfigMigrator:
    """配置迁移器"""

    MIGRATIONS: dict[str, Callable] = {
        # 从缺省/未声明版本迁移到 1.0.0
        "0.0.0": migrate_from_0_0_to_1_0,
        "0.9.0": migrate_from_0_9_to_1_0,
        "1.0.0": migrate_from_1_0_to_1_1,
    }

    def migrate(self, config: dict) -> dict:
        """从当前版本迁移到最新版本"""
        # 配置文件缺失 config_version 时视为 "0.0.0"，触发迁移
        current_version = config.get("config_version", "0.0.0")
        target_version = self._get_latest_version()

        while current_version != target_version:
            migration = self.MIGRATIONS.get(current_version)
            if migration is None:
                logger.warning(f"无法找到 {current_version} 的迁移路径，跳过")
                break
            config = migration(config)
            current_version = config["config_version"]

        return config
```

---

### 3.13 SubAgent Runtime — 隔离任务委派

每个长期 Agent 都具备 SubAgent 能力，用于把检索、工具、文件分析等事务性工作移出主会话上下文。SubAgent 是临时执行单元，不是 Agent Mesh 中的长期独立身份。

```text
Main Agent
  │ delegate_task(spec, policy)
  ▼
SubAgentSupervisor
  ├─ PolicyResolver：父权限 ∩ Agent 配置 ∩ Channel 策略 ∩ 子任务策略
  ├─ ContextPackager：只传任务、最小摘要和授权引用
  ├─ SubAgentRuntime：独立 Prompt / History / Budget / Workspace
  ├─ SubAgentJournal：追加式状态、工具、证据和错误日志
  └─ ResultBroker：结构化结果 + evidence_refs + usage → Main Agent
```

核心规则：

- 主 Agent 默认只接收 `SubAgentResult`，不接收完整工作历史；结果通过 `task_id` 与日志关联。
- 子 Agent 默认不继承陪伴人格、关系、情绪、完整聊天历史或长期记忆写权限。
- 子 Agent 的工具、模型、记忆和网络权限只能比父 Agent 更小，不能自行扩大。
- 日志记录可审计事实，不记录原始 reasoning；工具参数、结果和外部内容在持久化前脱敏、截断并生成证据引用。
- `list_subagent_runs` / `get_subagent_status` / `fetch_subagent_log` / `cancel_subagent` 让主 Agent 回答用户追问时复用既有执行记录。
- 子 Agent 默认不能直接向 Channel 发消息；用户可见进度由主 Agent 的 ProgressReporter 统一表达。
- `SubAgentSupervisor` 管理并发、递归、Token、墙钟时间、工具调用数、日志字节、工作区和制品保留期。

状态流：

```text
QUEUED → RUNNING → WAITING_TOOL → RUNNING
   ├→ SUCCEEDED
   ├→ FAILED
   ├→ CANCELLED
   └→ TIMED_OUT
```

现有 `TaskRunner` 仅复用主 Loop 和 Session，属于 H3 原型，不能视为该架构的完整实现。J4 将其迁移为独立 `SubAgentSupervisor` 与持久化运行模型。

---

## 五、消息生命周期

```
User 发送消息
    │
    ▼
[Channel Adapter] ───────────────────────────────────────────┐
    │ 封装为 ISACMessage                                     │
    │                                                        │
    ▼                                                        │
[EventBus.InterceptChain]  插件可拦截/修改 (ON_MESSAGE)      │
    │                                                        │
    ▼                                                        │
[🧭 MessageRouter]  ⬅ 消息归属哪个 Agent?                    │
    │  显式绑定 → 触发词 → 默认 Agent                        │
    │  剥离触发词，附带 agent_id                              │
    │                                                        │
    ▼                                                        │
[SessionManager]  查找/创建 Session                          │
    │  Session 的 key 包含 agent_id，因此先路由后建会话       │
    │  跨平台用户识别 (UserMapper)                            │
    │  加载 UserProfile                                       │
    │                                                        │
    ▼                                                        │
[AgentInstance]  进入该 Agent 的独立流水线                    │
    │                                                        │
    ▼                                                        │
[🚪 GatingSystem]  ⬅ 是否进入 Agent Loop?                   │
    │  Reply Necessity Score ≥ 80?                          │
    │  Idle Backoff 未生效?                                 │
    │  → TRIGGER                                             │
    │                                                        │
    ▼                                                        │
[SystemPromptBuilder]  组装 System Prompt                    │
    │  base_identity + personality_rules                     │
    │  + attention_drift + expression_style + mood           │
    │  + heuristic_memory (3min冷却)                         │
    │  + person_profile + jargon (每轮)                      │
    │  + skill_selector + tools_available                    │
    │                                                        │
    ▼                                                        │
[ISACAgentLoop.run()]                                        │
    │  hook: pre_llm → LLM.chat                              │
    │  if tool_calls:                                        │
    │    hook: pre_tool → exec_tool → hook: post_tool        │
    │    → ProgressEvent → ProgressReporter → Channel        │
    │      （频控/合并/脱敏/人格化；失败不阻塞主任务）         │
    │  else:                                                 │
    │    hook: final_response                                │
    │    return                                              │
    │                                                        │
    ▼                                                        │
[MemoryEncoder] (异步)                                        │
    │  提取 Episode → Embedding → 存储                       │
    │  更新 PersonProfile                                    │
    │  更新 Jargon                                           │
    │                                                        │
    ▼                                                        │
[EventBus.AsyncChain]  插件异步处理                          │
    │                                                        │
    ▼                                                        │
[Channel Adapter.send()] ────────────────────────────────────┘
    │
    ▼
User 收到回复
```

---

## 六、目录结构

```
ISAC/
├── pyproject.toml                  # 项目配置
├── uv.lock                         # 依赖锁定
├── README.md
├── LICENSE
├── Dockerfile
├── docker-compose.yml
│
├── isac/                           # 主包
│   ├── __init__.py                 # 版本号
│   ├── __main__.py                 # 入口
│   ├── main.py                     # 应用入口
│   │
│   ├── core/                       # 核心框架
│   │   ├── __init__.py
│   │   ├── events.py               # EventType 枚举
│   │   ├── types.py                # 核心类型定义
│   │   ├── injector.py             # PromptInjector 基类
│   │   ├── exceptions.py           # ISACError 错误体系
│   │   └── constants.py            # 常量
│   │
│   ├── locales/                    # 多语言支持 (i18n)
│   │   ├── __init__.py             # load_text() 工具函数
│   │   ├── zh_CN.py                # 中文 (默认)
│   │   └── en_US.py                # 英文
│   │
│   ├── channel/                    # Channel Layer
│   │   ├── __init__.py
│   │   ├── base.py                 # PlatformAdapter ABC
│   │   ├── model.py                # ISACMessage
│   │   ├── registry.py             # 适配器注册表
│   │   └── adapters/               # 平台适配器
│   │       ├── __init__.py
│   │       ├── qq_official/
│   │       ├── onebot/
│   │       ├── telegram/
│   │       ├── discord/
│   │       ├── wechat/
│   │       ├── wecom/
│   │       ├── slack/
│   │       ├── feishu/
│   │       └── ...                 # 更多平台
│   │
│   ├── gateway/                    # Gateway
│   │   ├── __init__.py
│   │   ├── event_bus.py            # EventBus (Intercept + Async)
│   │   ├── session.py              # SessionManager
│   │   ├── user_mapper.py          # 跨平台用户映射
│   │   ├── lock.py                 # SessionLockManager (并发控制)
│   │   └── models.py               # Session/Profile 数据模型
│   │
│   ├── router/                     # 消息路由 (Agent 归属)
│   │   ├── __init__.py
│   │   ├── router.py               # MessageRouter
│   │   ├── rules.py                # RoutingRules 持久化 + 热更新
│   │   └── types.py                # RoutingDecision / ChannelBinding
│   │
│   ├── gating/                     # 门控系统
│   │   ├── __init__.py
│   │   ├── system.py               # GatingSystem (门面)
│   │   ├── reply_necessity.py      # 回复必要性
│   │   ├── turn_scheduler.py       # 话轮调度
│   │   ├── turn_gates.py           # 触发门控
│   │   ├── idle_backoff.py         # 空闲退避
│   │   └── types.py                # GatingContext / GateDecision
│   │
│   ├── agent/                      # Agent Core
│   │   ├── __init__.py
│   │   ├── loop.py                 # ISACAgentLoop
│   │   ├── hooks.py                # AgentHooks / HookRegistry
│   │   ├── prompt_builder.py       # SystemPromptBuilder
│   │   ├── injector.py             # PromptInjector 兼容 re-export（新代码从 core.injector 导入）
│   │   ├── injectors/              # 内置注入器
│   │   │   ├── __init__.py
│   │   │   ├── base_identity.py    # Bot 基础身份
│   │   │   ├── attention_drift.py
│   │   │   ├── expression_style.py
│   │   │   ├── mood.py
│   │   │   ├── skill_selector.py
│   │   │   └── tools_available.py
│   │   └── tools/                  # 工具系统
│   │       ├── __init__.py
│   │       ├── registry.py         # AST 自动发现
│   │       ├── base.py             # Tool 基类
│   │       ├── social/             # 社交工具
│   │       │   ├── send_emoji.py
│   │       │   ├── send_image.py
│   │       │   ├── query_memory.py
│   │       │   ├── query_person_profile.py
│   │       │   ├── switch_chat.py
│   │       │   ├── wait.py
│   │       │   ├── fetch_history.py
│   │       │   └── view_forward_message.py
│   │       ├── utility/            # 实用工具
│   │       │   ├── bash.py
│   │       │   ├── read_file.py
│   │       │   ├── write_file.py
│   │       │   ├── web_search.py
│   │       │   └── task.py         # 子 Agent 委派
│   │       └── mcp/                # MCP 工具
│   │           ├── __init__.py
│   │           └── client.py
│   │
│   ├── commands/                   # 命令系统 (用户/管理命令)
│   │   ├── __init__.py
│   │   ├── base.py                 # Command 基类
│   │   ├── registry.py             # CommandRegistry (按 Agent/Channel 启停)
│   │   └── builtin/                # 内置命令 (/focus /agents /mute ...)
│   │
│   ├── runtime/                    # 多 Agent 运行时
│   │   ├── __init__.py
│   │   ├── instance.py             # AgentInstance
│   │   ├── manager.py              # AgentManager (生命周期)
│   │   ├── assembly.py             # 按 AgentConfig 组装子系统
│   │   ├── config.py               # AgentConfig / 配置分层加载
│   │   ├── progress.py             # ProgressEvent / ProgressReporter
│   │   ├── bus.py                  # InterAgentBus (Agent 互联)
│   │   └── subagent/               # 隔离子任务运行时
│   │       ├── models.py           # Task/Run/Event/Result/Policy
│   │       ├── supervisor.py       # 派发、并发、取消与恢复
│   │       ├── context.py          # 最小上下文打包
│   │       ├── journal.py          # 持久化追加日志
│   │       └── broker.py           # 结果与证据回传
│   │
│   ├── memory/                     # Memory System
│   │   ├── __init__.py
│   │   ├── pipeline.py             # MemoryRetrievalPipeline
│   │   ├── embedder.py             # EmbeddingManager
│   │   ├── reranker.py             # Reranker
│   │   ├── injector/               # 记忆注入策略
│   │   │   ├── __init__.py
│   │   │   ├── heuristic.py        # HeuristicMemoryInjector
│   │   │   ├── mid_term.py         # MidTermMemoryInjector
│   │   │   ├── person_profile.py   # PersonProfileInjector
│   │   │   └── jargon.py           # JargonInjector
│   │   ├── storage/                # 存储引擎
│   │   │   ├── __init__.py
│   │   │   ├── vector.py           # VectorStore (sqlite-vec)
│   │   │   ├── metadata.py         # MetadataStore (SQLite+FTS5)
│   │   │   ├── graph.py            # GraphStore
│   │   │   └── sparse.py           # SparseBM25Index
│   │   └── consolidator.py         # 后台整合
│   │
│   ├── persona/                    # 人格系统 (纯 Prompt 注入)
│   │   ├── __init__.py
│   │   ├── manager.py              # PersonaManager
│   │   ├── drift_profiles.py       # 注意力漂移配置
│   │   ├── style_profiles.py       # 表达风格配置
│   │   ├── mood.py                 # 情绪状态模型 (由 agent/injectors/mood.py 读取)
│   │   └── behavior_learner.py     # BehaviorLearner (注册 FINAL_RESPONSE hook)
│   │
│   ├── plugin/                     # Plugin System
│   │   ├── __init__.py
│   │   ├── compatibility/          # 插件兼容层
│   │   │   ├── __init__.py
│   │   │   ├── astrbot/            # AstrBot 兼容
│   │   │   │   ├── __init__.py
│   │   │   │   ├── star.py         # Star 基类
│   │   │   │   ├── context.py      # Context API 模拟
│   │   │   │   ├── events.py       # EventType 映射
│   │   │   │   ├── tools.py        # FunctionTool 桥接
│   │   │   │   └── sandbox.py      # Import 重定向
│   │   │   └── maibot/             # MaiBot 兼容
│   │   │       ├── __init__.py
│   │   │       ├── plugin.py       # Plugin 基类映射
│   │   │       ├── actions.py      # Action → Tool / Hook
│   │   │       └── commands.py     # Command → ISAC Command
│   │   ├── native/                 # ISAC 原生 SDK
│   │   │   ├── __init__.py
│   │   │   ├── plugin.py           # ISACPlugin 基类
│   │   │   ├── hooks.py            # 插件钩子
│   │   │   └── api.py              # 公开 API
│   │   └── runtime/                # 插件运行时
│   │       ├── __init__.py
│   │       ├── manager.py          # PluginManager
│   │       └── loader.py           # 插件加载器
│   │
│   ├── provider/                   # Provider Layer
│   │   ├── __init__.py
│   │   ├── base.py                 # Provider 基类
│   │   ├── manager.py              # ProviderManager
│   │   ├── catalog.py              # ModelCatalog / ModelDescriptor
│   │   ├── router.py               # 按能力/授权/健康/成本/延迟选模型
│   │   ├── llm/                    # LLM / Vision Providers
│   │   ├── embed/                  # Embedding Providers
│   │   ├── rerank/                 # Reranking Providers
│   │   ├── speech/                 # STT / TTS Providers
│   │   ├── image/                  # Image Generation Providers
│   │   └── video/                  # Video Understanding / Generation Providers
│   │
│   ├── artifacts/                  # 多模态制品存储、保留期、授权下载
│   │   ├── models.py               # ArtifactRef
│   │   └── store.py                # ArtifactStore
│   │
│   ├── observability/              # 指标、告警与模型用量
│   │   └── usage/                  # recorder/storage/pricing/models
│   │
│   ├── control/                    # 控制面 (管理自动化，商业化预留)
│   │   ├── __init__.py
│   │   ├── api/                    # Admin REST API (FastAPI)
│   │   │   ├── __init__.py
│   │   │   ├── server.py
│   │   │   ├── routes_agents.py
│   │   │   ├── routes_routing.py
│   │   │   └── routes_plugins.py
│   │   ├── mcp_server.py           # ISAC 作为 MCP 服务端
│   │   ├── webhooks.py             # 事件推送 / 自动化触发
│   │   └── auth.py                 # Token 认证
│   │
│   └── utils/                      # 工具
│       ├── __init__.py
│       ├── logger.py               # 日志
│       ├── config.py               # 配置加载
│       ├── security.py             # API Key 加密 (AES-256-GCM)
│       └── helpers.py
│
├── plugins/                        # 第三方插件目录
│   ├── .gitkeep
│   └── README.md
│
├── data/                           # 运行数据 (gitignored)
│   ├── config.jsonc                # 全局配置
│   ├── agents/                     # 多 Agent
│   │   ├── registry.jsonc          # Agent 注册表
│   │   └── <agent_id>/
│   │       ├── config.jsonc        # 该 Agent 独立配置
│   │       └── memory/             # 该 Agent 记忆数据
│   ├── routing.jsonc               # 路由规则 (绑定 / 默认 Agent)
│   ├── links.jsonc                 # Agent 互联 Link
│   ├── memory/                     # 共享记忆命名空间 ("shared", 可选)
│   │   ├── metadata.db
│   │   └── vectors/
│   └── sessions/
│
├── tests/                          # 测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_prompt_builder.py
│   │   ├── test_agent_loop.py
│   │   ├── test_gating.py
│   │   ├── test_memory_pipeline.py
│   │   └── ...
│   ├── integration/
│   │   ├── test_full_flow.py
│   │   ├── test_plugin_compat.py
│   │   └── ...
│   └── fixtures/
│
└── scripts/                        # 工具脚本
    ├── migrate.py                  # 数据迁移
    └── export.py                   # 数据导出
```

---

## 七、设计决策记录

### ADR-001: 为什么不用 Leader 进程？

**上下文**: grok-build 使用 Leader 进程让多个客户端共享一个推理连接。

**决策**: ISAC 不采用 Leader 进程。

**原因**: Bot 场景通常单实例运行，不需要多客户端共享。引入 Leader 会增加状态同步、断线重连、Unix Socket 通信的复杂度，收益不明显。

### ADR-002: 为什么 Prompt 注入而不是代码中间件？

**上下文**: 拟人能力（注意力漂移、回复风格等）可以用代码变换实现。

**决策**: 通过 System Prompt 注入实现。

**原因**:
- Prompt 注入让 LLM **自己决定**如何表现，更自然
- 代码变换会产生"机器人感"——伪装的人格
- 修改 Prompt 指令比修改代码规则更容易调整效果
- 注入是声明式的，易于测试和调试

### ADR-003: 为什么不用独立向量数据库？

**上下文**: 生产级 RAG 通常用 Qdrant/Milvus。

**决策**: 使用 sqlite-vec 嵌入式方案。

**原因**:
- 个人/小型部署，不需要独立进程
- 减少运维复杂度
- 数据一致性更好（SQLite 事务）
- 支持零配置部署

### ADR-004: 为什么门控先于 Agent？

**上下文**: 可以在 Agent 内部决定是否回复。

**决策**: 门控独立在 Agent 之前。

**原因**:
- 减少不必要的 LLM 调用（Token 成本）
- 门控决策需要访问 Runtime 状态（频率、积压等），Agent 不应该关心这些
- 测试时可以单独测门控逻辑

### ADR-005: 为什么 AstrBot 兼容而不是重写？

**上下文**: AstrBot 插件生态成熟，有用户基础。

**决策**: 实现 AstrBot Star/Context API 兼容层。

**原因**:
- 直接复用现有插件生态，不需要用户重写插件
- 降低用户迁移成本
- 兼容层的投入 < 重建生态的投入

### ADR-006: 为什么多语言 (i18n) 通过 locales/ 实现？

**上下文**: 拟人 Prompt 指令（注意力漂移、人格规则等）需要支持多语言。

**决策**: 使用独立的 `locales/` 目录，通过 `load_text(key, locale)` 获取本地化文本。

**原因**:
- 与 MaiBot 的方式一致，方便参考
- 注入器只需要 key，不需要关心具体语言
- 支持动态切换语言（如根据用户偏好或平台）

**使用方式**:
```python
# 注入器中使用
from isac.locales import load_text

drift_rule = load_text("attention_drift.subtle", locale="zh_CN")
# 返回: "漂移档位：轻微漂移。只在最近消息里出现非常自然的触发点时..."
```

### ADR-007: 为什么单进程多 Agent 而不是多进程？

**上下文**: 多 Agent 可以用每个 Agent 一个进程实现。

**决策**: 单进程内运行多个 AgentInstance。

**原因**:
- 共享 Channel 连接（一个 QQ 账号服务多个 Agent）在多进程下需要额外 IPC
- Provider 连接池 / 嵌入模型可在进程内共享，降低内存与成本
- 单机部署保持简单（简洁优先）
- 隔离性通过实例级组装（无共享可变状态）保证；需要更强隔离时可按 agent_id 拆分部署

### ADR-008: 为什么 Channel 连接与 Agent 解耦？

**上下文**: 一个 IM 连接（如一个 QQ Bot）要服务多个 Agent；一个 Agent 也要连接多个 IM。

**决策**: Channel 连接是共享资源，MessageRouter 按规则把消息路由到 Agent。

**原因**:
- IM 账号是稀缺资源（QQ 需要独立账号 / 手机验证）
- 路由规则（绑定 / 触发词 / 默认 Agent）可热更新，无需重启连接
- Agent 与 IM 的绑定关系成为纯配置，可被控制面自动化管理

### ADR-009: 为什么 Agent 互联用显式 Link + 总线？

**上下文**: Agent 间通信可以互相直接调用方法。

**决策**: InterAgentBus 统一转发，必须配置 Link (ACL) 才能通信。

**原因**:
- 默认不互通，避免 Agent 间意外串话 / Prompt 污染
- 总线是天然审计点：所有互联消息可记录、可拦截、可挂钩子
- Link 配置可热更新，配合控制面实现自动化编排

### ADR-010: 为什么同时兼容 AstrBot 和 MaiBot，还要原生 SDK？

**上下文**: AstrBot 与 MaiBot 都有成熟插件生态，但能力模型不同。

**决策**: 双兼容层 + ISAC Native SDK v2 并存。

**原因**:
- 兼容层最大化复用存量生态，降低用户迁移成本
- MaiBot 插件（Action / Command 模型）与 AstrBot（Star / Event 模型）互补
- 兼容层只能覆盖共性能力；互联钩子、命令、管理面扩展等 ISAC 独有能力由原生 SDK 承载
- 三种格式在同一沙箱 / 权限体系下运行

### ADR-011: 为什么控制面独立于数据面？

**上下文**: 商业化需要通过 API 触发自动化（创建 Agent、绑定 IM、修改参数）。

**决策**: Admin REST API + ISAC MCP Server + Webhooks 组成独立控制面。

**原因**:
- 控制面操作全部复用 AgentManager / Router / Bus 的公开方法，不与消息处理耦合
- MCP Server 让外部 Agent 系统也能管理 ISAC（顺应 MCP 生态）
- 默认 127.0.0.1 + Token，攻击面可控
- 预留 Workflow 编排与插件 Admin Routes，支撑未来商业化功能

---

## 八、非功能性需求

| 维度 | 要求 |
|------|------|
| **性能** | 消息处理延迟 < 5s（不含 LLM 推理与门控主动 DELAY；DELAY 是框架有意推迟，不计入处理延迟） |
| **并发** | 支持多平台同时连接，单实例 100+ 并发会话 |
| **可靠性** | 单会话故障不影响其他会话；记忆写入失败不阻塞消息流 |
| **可扩展性** | 新平台适配器只需实现 `PlatformAdapter` 接口 |
| **可维护性** | 每个子系统可独立测试；模块间通过明确接口通信 |
| **安全性** | 插件沙箱隔离；敏感信息 (API Key) 加密存储 |
| **可观测性** | 结构化日志 (structlog)；关键事件带上下文信息 |
| **多实例** | 单进程 10+ Agent 实例，互不影响 |
| **隔离性** | Agent 间记忆/配置/工具权限隔离；共享命名空间需显式启用 |
| **自动化** | 核心管理操作 100% 可通过 Admin API / MCP 完成 |
