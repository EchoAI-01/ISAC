# ISAC 技术规范

> 数据模型、接口契约、配置规范、协议定义

---

## 目录

- [一、核心数据模型](#一核心数据模型)
- [二、接口契约](#二接口契约)
- [三、配置规范](#三配置规范)
- [四、协议定义](#四协议定义)
- [五、错误处理规范](#五错误处理规范)
- [六、专项规范索引](#六专项规范索引)

---

## 一、核心数据模型

### 1.1 ISACMessage — 统一消息模型

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ISACMessage:
    """跨平台统一消息模型"""

    # 基础信息
    msg_id: str                              # 消息 ID
    platform: str                            # 平台标识 ("qq", "telegram", ...)
    timestamp: int                           # 消息时间戳 (Unix)

    # 用户信息
    user_id: str                             # 平台内用户 ID
    user_name: str                           # 用户昵称 (可读)
    group_id: Optional[str] = None           # 群聊 ID (私聊为 None)
    group_name: Optional[str] = None         # 群聊名称

    # 内容
    content: str                             # 纯文本内容
    segments: list[MessageSegment] = field(default_factory=list)  # 富媒体分段

    # 会话
    session_id: str = ""                     # 全局统一会话 ID (由 SessionManager 分配)
    reply_to: Optional[str] = None           # 回复的目标消息 ID

    # 元数据
    metadata: dict = field(default_factory=dict)  # 平台特定元数据

    @property
    def is_private_chat(self) -> bool:
        """是否私聊消息 (group_id 为 None)"""
        return self.group_id is None

    def has_at(self, bot_id: str) -> bool:
        """消息中是否 @ 了指定用户 (通常传 bot 自身 ID)"""
        return any(
            seg.type == "at" and seg.data.get("user_id") == bot_id
            for seg in self.segments
        )

    def has_mention(self, names: list[str]) -> bool:
        """消息文本中是否以纯文本形式提及指定名称（不含 @）。

        用于私聊场景下的门控强制触发：用户直接叫 Bot 名字也算 "提及"。
        """
        if not self.content or not names:
            return False
        lower = self.content.lower()
        return any(name.lower() in lower for name in names if name)


@dataclass
class MessageSegment:
    """消息分段 (用于富媒体)"""
    type: str                                # "text" | "image" | "at" | "reply" | "emoji" | "voice"
    data: dict                               # 分段内容
```

### 1.2 Session — 会话

```python
@dataclass
class Session:
    """ISAC 会话"""

    session_id: str                          # 全局唯一会话 ID
    user_id: str                             # 主用户 ID (跨平台统一)
    user_ids: dict[str, str] = field(default_factory=dict)  # 各平台 user_id 映射
    agent_id: str = ""                       # 所属 Agent (多 Agent 架构)
    platform: str = ""                       # 当前交互平台
    group_id: Optional[str] = None           # 群聊 ID
    is_group: bool = False                   # 是否群聊

    created_at: int = 0                      # 创建时间
    last_active: int = 0                     # 最后活跃时间
    state: str = "active"                    # "active" | "idle" | "closed"

    # 运行时状态 (不持久化)
    context: Optional[SessionContext] = None


@dataclass
class SessionContext:
    """会话运行时上下文"""

    budget: Budget                           # LLM 调用预算
    interrupt_requested: bool = False        # 是否请求中断
    iteration: int = 0                       # 当前迭代次数
    reasoning_content: str = ""              # 推理内容
    pending_messages: list[ISACMessage] = field(default_factory=list)


@dataclass
class Budget:
    """LLM 调用预算（同时跟踪迭代次数和 Token）"""
    max_iterations: int = 10                 # 最大迭代次数
    max_tokens: int = 8000                   # 最大 token 数
    remaining_iterations: int = 10           # 剩余迭代次数
    used_tokens: int = 0                     # 已用 token 数

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def remaining(self) -> bool:
        """是否还有预算（迭代和 Token 都要有余量）"""
        return self.remaining_iterations > 0 and self.remaining_tokens > 0

    def consume(self, usage: TokenUsage) -> None:
        """消费一次调用，同时更新迭代次数和 Token 数"""
        self.remaining_iterations -= 1
        self.used_tokens += usage.total_tokens
```

### 1.3 UserProfile — 用户画像

```python
@dataclass
class UserProfile:
    """用户画像 (跨平台统一)"""

    user_id: str                             # 主用户 ID
    platform_ids: dict[str, str]             # 各平台 ID 映射

    nickname: str = ""                       # 昵称
    relationship_depth: float = 0.0          # 关系深度 0.0~1.0
    interaction_count: int = 0               # 交互次数
    first_seen: int = 0
    last_seen: int = 0

    # 行为特征
    expression_style: dict = field(default_factory=dict)  # 表达风格偏好
    preferences: dict = field(default_factory=dict)       # 话题/回复偏好
    behavior_patterns: list[dict] = field(default_factory=list)

    # 内容特征
    jargon_set: list[str] = field(default_factory=list)   # 用户常用行话
    topics_of_interest: list[str] = field(default_factory=list)

    # 嵌入
    embedding: Optional[list[float]] = None   # 用户画像向量
```

### 1.4 MemoryHit — 记忆命中

```python
@dataclass
class MemoryHit:
    """记忆检索结果"""

    id: str                                  # 记忆 ID
    content: str                             # 记忆内容
    source: str                              # 来源 (session_id)
    hit_type: str                            # "episode" | "paragraph" | "person_fact"
    score: float                             # 匹配分数
    metadata: dict = field(default_factory=dict)
    embedding: Optional[list[float]] = None
```

### 1.5 消息流状态

```python
from enum import Enum

class MessageStatus(Enum):
    """消息处理状态"""
    RECEIVED = "received"            # 已接收
    ROUTED = "routed"                # 已路由到会话
    GATED = "gated"                  # 门控决策完成
    PROCESSING = "processing"        # Agent 处理中
    RESPONDING = "responding"        # 发送回复中
    COMPLETED = "completed"          # 完成
    DROPPED = "dropped"              # 被丢弃 (门控拒绝)
    ERROR = "error"                  # 处理出错
```

### 1.6 AgentConfig / AgentInstance — Agent 配置与实例

```python
@dataclass
class AgentConfig:
    """单个 Agent 的独立配置 (data/agents/<agent_id>/config.jsonc)"""

    agent_id: str
    display_name: str = ""
    enabled: bool = True

    # 人格 / 门控: 覆盖全局配置的子集
    persona: dict = field(default_factory=dict)
    gating: dict = field(default_factory=dict)

    # 记忆命名空间: 默认 = agent_id; "shared" 表示跨 Agent 共享
    memory_namespace: str = ""

    # LLM: None = 使用全局默认 Provider; 否则该 Agent 独立 Provider 配置
    llm: dict | None = None

    # 路由触发词: 消息以这些词开头时路由到本 Agent
    trigger_words: list[str] = field(default_factory=list)

    # 能力开关: 插件 / 工具 / 命令 / MCP, 按 Agent 独立配置
    plugins_allow: list[str] = field(default_factory=lambda: ["*"])
    plugins_deny: list[str] = field(default_factory=list)
    tools_policy: dict = field(default_factory=dict)      # 覆盖全局工具权限
    commands_allow: list[str] = field(default_factory=lambda: ["*"])
    mcp_servers: list[str] = field(default_factory=list)  # 允许使用的 MCP Server 名


@dataclass
class AgentInstance:
    """运行中的 Agent (组装细节见 ARCHITECTURE.md 3.1)"""
    agent_id: str
    config: AgentConfig
    status: str = "stopped"           # "running" | "stopped" | "error"
```

### 1.7 RoutingRule / ChannelBinding — 路由

```python
@dataclass
class ChannelBinding:
    """显式绑定: 某平台某会话固定归属某 Agent (路由优先级最高)"""
    platform: str
    agent_id: str
    group_id: str | None = None       # 与 user_id 都为 None 表示整个平台
    user_id: str | None = None


@dataclass
class RoutingRules:
    """路由规则集 (data/routing.jsonc, 控制面可热更新)"""
    bindings: list[ChannelBinding] = field(default_factory=list)
    default_agents: dict[str, str] = field(default_factory=dict)  # platform -> agent_id
    # trigger_words 在各 AgentConfig 中定义


@dataclass
class RoutingDecision:
    """路由结果"""
    agent_id: str
    matched_by: str                   # "binding" | "trigger_word" | "default"
    content: str                      # 剥离触发词后的内容
```

### 1.8 InterAgentLink / InterAgentMessage — Agent 互联

```python
@dataclass
class InterAgentLink:
    """Agent 互联链路 (data/links.jsonc, ACL)"""
    from_agent: str
    to_agent: str
    direction: str = "both"           # "both" | "oneway"
    enabled: bool = True
    permissions: list[str] = field(default_factory=list)  # ask | notify | handoff | memory_query
    visible_memory_scopes: list[str] = field(default_factory=list)
    max_context_messages: int = 20


@dataclass
class InterAgentMessage:
    """Agent 间消息"""
    from_agent: str
    to_agent: str
    type: str                         # "request" | "response" | "notify" | "handoff" | "memory_query"
    content: str
    context: dict = field(default_factory=dict)
    trace_id: str = ""
```

### 1.9 专项数据模型

以下模型在专项文档中定义，核心契约实现时应与对应文档保持一致：

| 模型 | 文档 | 说明 |
|------|------|------|
| `ConversationRuntime` / `WaitState` / `ProactiveTask` | [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md) | 会话级拟人化运行时、等待与主动任务 |
| `MemoryItem` / `PlatformIdentity` / `PersonIdentity` | [MEMORY_DESIGN.md](./MEMORY_DESIGN.md) | 记忆条目、跨平台身份归一 |
| 扩展 `RoutingDecision` | [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md) | primary / observer / candidate Agent 路由结果 |
| `PluginContext` / 权限类型 | [PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md) | 插件上下文、权限与生命周期 |
| `AuditEvent` / Webhook payload | [CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md) | 控制面审计、Webhook 与 MCP 返回格式 |

---

## 二、接口契约

### 2.1 PlatformAdapter — 平台适配器

```python
from abc import ABC, abstractmethod

class PlatformAdapter(ABC):
    """平台适配器抽象基类。所有平台适配器必须实现此接口。"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台唯一标识"""
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动平台连接，开始接收消息"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止平台连接，清理资源"""
        ...

    @abstractmethod
    async def send(self, message: ISACMessage) -> bool:
        """发送消息到平台。返回是否成功。"""
        ...

    # 框架注册的回调 (由 Gateway 调用)
    on_message: Callable[[ISACMessage], Awaitable[None]] | None = None
    on_error: Callable[[Exception], Awaitable[None]] | None = None
```

### 2.2 PromptInjector — Prompt 注入器

```python
from abc import ABC

# PromptInjector 位于 isac/core/injector.py，
# 使 memory/injector/ 与 agent/injectors/ 都能单向依赖 core。
class PromptInjector(ABC):
    """Prompt 注入器抽象基类（与 ARCHITECTURE.md 3.4 / isac/core/injector.py 一致）。

    除 `key` 与 `build()` 外，各属性均提供默认实现，子类按需覆写。
    每个子系统实现此基类来注入 Prompt 块。
    """

    @property
    def key(self) -> str:
        """注入器唯一标识"""
        ...

    @property
    def priority(self) -> int:
        """注入优先级 (数字越大越先注入)"""
        ...

    @property
    def max_frequency_seconds(self) -> float:
        """最小触发间隔 (秒)。0 = 每次"""
        ...

    @property
    def max_new_messages(self) -> int:
        """最小新消息数。0 = 不限制"""
        ...

    @property
    def enabled(self) -> bool:
        """是否启用"""
        ...

    @property
    def tokens_estimate(self) -> int:
        """预估 token 数 (用于预算管理)"""
        ...

    async def build(self, context: InjectionContext) -> str:
        """构建注入文本。返回空字符串表示不注入。"""
        ...
```

### 2.3 LLMProvider — LLM 提供商

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class LLMProvider(ABC):
    """LLM 提供商抽象基类"""

    @abstractmethod
    async def chat(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> LLMResponse:
        """非流式聊天请求"""
        ...

    @abstractmethod
    def chat_stream(
        self,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        """流式聊天请求，返回 chunk 迭代器"""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """返回当前使用的模型名称"""
        ...

    @abstractmethod
    def get_capabilities(self) -> ModelCapabilities:
        """返回模型能力"""
        ...


@dataclass
class LLMChunk:
    """流式响应的单个块"""
    delta_content: str = ""                     # 增量文本
    delta_reasoning: str = ""                   # 增量推理内容
    tool_call: ToolCall | None = None           # 完整的工具调用（只在 finish_reason=tool_calls 时出现）
    finish_reason: str | None = None            # "stop" | "tool_calls" | "length"
    usage: TokenUsage = field(default_factory=lambda: TokenUsage())


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str                            # 文本内容
    reasoning: str = ""                     # 推理内容 (如 o1/o3 模型)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: dict


@dataclass
class TokenUsage:
    """Token 使用情况"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

### 2.4 MemoryRetrievalPipeline — 记忆检索

```python
class MemoryRetrievalPipeline:
    """记忆检索流水线契约"""

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filters: dict | None = None,
        agent_id: str = "",
        user_id: str = "",
        group_id: str = "",
    ) -> list[MemoryHit]:
        """
        检索记忆。

        Args:
            query: 查询文本
            top_k: 返回结果数
            filters: 元数据过滤条件
            agent_id: 记忆命名空间 (默认当前 Agent; "shared" = 跨 Agent 共享)
            user_id: 用户 ID (用于权限过滤)
            group_id: 群组 ID (用于权限过滤)

        Returns:
            按相关性排序的记忆列表
        """
        ...

    async def store_episode(
        self,
        content: str,
        session_id: str,
        user_id: str,
        agent_id: str = "",
        metadata: dict | None = None,
    ) -> str:
        """存储一条情景记忆 (写入 agent_id 命名空间)。返回记忆 ID。"""
        ...


class EmbeddingProvider(ABC):
    """嵌入模型提供商契约"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化"""
        ...

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """查询文本向量化"""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """返回向量维度"""
        ...


class RerankerProvider(ABC):
    """重排序模型提供商契约"""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[str],
    ) -> list[float]:
        """对候选文本重排序，返回相关性分数列表"""
        ...
```

### 2.5 并发控制

```python
class SessionLockManager:
    """会话级锁管理器。同一会话的消息串行处理，避免状态冲突。"""

    def __init__(self) -> None:
        # 实例级字典，避免多实例共享可变默认值
        self._locks: dict[str, asyncio.Lock] = {}
        self._agent_running: dict[str, bool] = {}
        self._queues: dict[str, list[ISACMessage]] = {}

    async def acquire(self, session_id: str) -> asyncio.Lock:
        """获取会话锁"""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def is_agent_running(self, session_id: str) -> bool:
        """检查该会话是否有 Agent 在运行"""
        return self._agent_running.get(session_id, False)

    def set_agent_running(self, session_id: str, running: bool) -> None:
        self._agent_running[session_id] = running

    async def handle_message(self, message: ISACMessage, handler: Callable):
        """统一消息处理入口，保证同一会话串行"""
        lock = await self.acquire(message.session_id)
        async with lock:
            if self.is_agent_running(message.session_id):
                # 选项 A: 排队等待（推荐，MaiBot 做法）
                await self._queue_message(message)
                return
            self.set_agent_running(message.session_id, True)
            try:
                await handler(message)
            finally:
                self.set_agent_running(message.session_id, False)
                await self._process_queued(message.session_id)
```

### 2.6 Plugin Manifest

ISAC 原生插件的 manifest 格式 (JSONC):

```jsonc
{
    "name": "my_plugin",
    "version": "1.0.0",
    "description": "插件描述",
    "author": "作者名",
    "isac_version": ">=1.0.0",      // 兼容的 ISAC 版本范围 (PEP 440)
    "entry": "plugin.py",           // 入口文件
    "hooks": ["pre_llm", "post_tool"],   // 声明使用的 Agent hooks
    "tools": ["my_tool"],           // 声明提供的工具
    "injectors": ["my_injector"],   // 声明提供的注入器
    "commands": ["my_command"],     // 声明提供的命令 (原生 SDK)
    "inter_agent_hooks": ["on_inter_agent_message"],  // 互联钩子 (原生 SDK)
    "admin_routes": ["/my_plugin/status"],            // 预留: 管理端点 (原生 SDK)
    "permissions": [                 // 声明申请的权限
        "filesystem:read:data/",
        "network:https",
    ],
    "config_schema": {               // 配置 Schema (用于自动生成配置界面)
        "type": "object",
        "properties": {
            "api_key": {"type": "string", "description": "API Key"},
        },
    },
}
```

### 2.7 AstrBot 兼容接口

```python
# AstrBot Star 兼容
class Star:
    """兼容 astrbot.api.star.Star"""

    def __init__(self, context: StarContext):
        self.context = context

    async def terminate(self):
        """插件卸载时调用"""


class StarContext:
    """兼容 AstrBot Context 对象"""

    async def send_message(self, message: str, platform: str | None = None):
        """发送消息 (映射到 ISAC Channel)"""

    def get_platform(self, platform_name: str) -> PlatformAdapter | None:
        """获取平台适配器"""

    def get_provider(self, provider_name: str | None = None) -> LLMProvider | None:
        """获取 LLM Provider"""


# AstrBot EventType 兼容 (映射到 EventBus 事件)
class EventType:
    """AstrBot 事件类型枚举 → ISAC EventBus 映射

    注意: AstrBot 的 LLM 事件 (OnLLMRequestEvent 等) 映射到 ISAC
    AgentHooks (非 EventBus)，通过 Agent 循环内部的 hook 触发。
    """

    # 消息事件 (映射到 EventBus)
    OnMessageEvent = "on_message"
    OnAstrBotLoadedEvent = "on_astrbot_loaded"
    OnDecoratingResultEvent = "on_decorating_result"
    OnAfterSendMessage = "on_after_send"
    OnBeforeMessageEvent = "on_before_message"
    OnAfterMessageEvent = "on_after_message"

    # LLM 事件 (映射到 AgentHooks，不经过 EventBus)
    OnLLMRequestEvent = "on_llm_request"        # → AgentHooks.PRE_LLM
    OnAfterLLMResponseEvent = "on_after_llm_response"  # → AgentHooks.POST_LLM
```

### 2.8 AgentManager — Agent 生命周期

```python
class AgentManager:
    """Agent 生命周期管理契约。

    所有公开方法同时暴露给 Admin API 与 ISAC MCP Server (控制面)，
    control/ 不得复制业务逻辑。
    """

    async def create(self, config: AgentConfig) -> AgentInstance: ...
    async def start(self, agent_id: str) -> None: ...
    async def stop(self, agent_id: str) -> None: ...
    async def destroy(self, agent_id: str, *, keep_memory: bool = True) -> None: ...
    async def get(self, agent_id: str) -> AgentInstance | None: ...
    async def list(self) -> list[AgentInstance]: ...
    async def reload_config(self, agent_id: str, config: AgentConfig) -> None: ...
```

### 2.9 MessageRouter — 消息路由

```python
class MessageRouter:
    """消息路由契约 (路由优先级见 ARCHITECTURE.md 3.2)"""

    async def route(self, message: ISACMessage) -> RoutingDecision | None:
        """返回目标 Agent; None 表示 DROP"""

    def set_rules(self, rules: RoutingRules) -> None:
        """热更新路由规则 (持久化到 data/routing.jsonc)"""

    def get_rules(self) -> RoutingRules: ...

    def register_router_hook(self, fn: Callable) -> None:
        """预留: 自定义路由函数 (Native SDK)，在显式绑定之前执行"""
```

### 2.10 InterAgentBus — Agent 互联

```python
class InterAgentBus:
    """Agent 互联总线契约。默认不互通，必须显式配置 Link。"""

    async def send(self, message: InterAgentMessage) -> InterAgentMessage | None:
        """检查 Link ACL → 投递到目标 Agent → 返回响应 (notify 类型返回 None)"""

    def add_link(self, link: InterAgentLink) -> None: ...
    def remove_link(self, from_agent: str, to_agent: str) -> None: ...
    def can_talk(self, from_agent: str, to_agent: str) -> bool: ...
    def list_links(self) -> list[InterAgentLink]: ...
```

### 2.11 CommandRegistry — 命令系统

```python
class Command(ABC):
    """命令基类 (用户斜杠命令 / 管理命令)"""

    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def usage(self) -> str: ...

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """执行命令，返回回复文本"""


class CommandRegistry:
    """命令注册表。命令可按 Agent / Channel 独立启停。"""

    def register(self, command: Command) -> None: ...
    async def try_execute(self, message: ISACMessage, agent_id: str) -> str | None:
        """消息以 '/' 开头时尝试执行; 未命中或已禁用返回 None"""
    def is_enabled(self, name: str, agent_id: str, platform: str) -> bool: ...

# 内置命令: /focus /agents /use <agent_id> /mute /unmute
```

---

## 三、配置规范

### 3.1 配置格式

使用 **JSONC** (JSON with Comments)，支持注释：

```jsonc
// ISAC 主配置
{
    // 基础配置
    "debug": false,
    "log_level": "info",        // "debug" | "info" | "warning" | "error"

    // 平台配置
    "platforms": {
        "qq": {
            "enabled": true,
            "app_id": "...",
            "app_secret": "...",
        },
        "telegram": {
            "enabled": false,
            "bot_token": "...",
        },
    },

    // LLM 配置
    "llm": {
        "provider": "openai",           // "openai" | "anthropic" | "google" | ...
        "model": "gpt-4o",
        "fallback_model": "gpt-4o-mini",
        "api_key": "...",
        "base_url": "...",
        "max_tokens": 4096,
        "temperature": 0.7,
    },

    // 门控配置
    "gating": {
        "reply_necessity_threshold": 80,     // 回复必要性阈值
        "trigger_threshold": 3,              // 触发阈值 (消息数)
        "idle_backoff_base_seconds": 30,     // 空闲退避基础时间
        "idle_backoff_cap_seconds": 300,     // 空闲退避上限
    },

    // 记忆配置
    "memory": {
        "enabled": true,
        "embedding": {
            "provider": "fastembed",         // "fastembed" | "sentence_transformers" | "openai"
            "model": "bge-small-zh-v1.5",
            "dimension": 512,
        },
        "reranker": {
            "enabled": true,
            "provider": "bge-reranker-v2-m3", // 或 "cohere" | "jina" | "none"
        },
        "heuristic": {
            "enabled": true,
            "frequency_seconds": 180,         // 3 分钟
            "min_new_messages": 60,
            "limit": 3,
        },
        "person_profile": {
            "enabled": true,
            "max_profiles": 3,
        },
        "jargon": {
            "enabled": true,
        },
    },

    // 人格配置
    "persona": {
        "attention_drift": {
            "enabled": true,
            "level": "subtle",              // "subtle" | "active" | "scattered" | "wild"
            "anchor_policy": "balanced",    // "strict" | "balanced" | "loose"
            "reaction_style": "natural",    // "reserved" | "natural" | "lively"
        },
        "expression_style": {
            "formality": 0.5,               // 0.0=随意 ~ 1.0=正式
            "verbosity": 0.5,               // 0.0=简洁 ~ 1.0=详尽
            "humor": 0.5,                   // 0.0=严肃 ~ 1.0=幽默
            "empathy": 0.7,                 // 0.0=理性 ~ 1.0=感性
        },
    },

    // 插件配置
    "plugins": {
        "enabled": true,
        "dir": "plugins/",
        "auto_load": true,
        "compat_astrbot": true,             // 启用 AstrBot 兼容
    },
}
```

### 3.2 配置加载规则

**加载顺序** (后面的覆盖前面的):

1. 内置默认值
2. `data/config.jsonc` (用户配置)
3. 环境变量覆盖 (`ISAC_LLM_API_KEY`, `ISAC_DEBUG`, ...)
4. CLI 参数覆盖 (`--debug`, `--model gpt-4o`, ...)

**环境变量映射**:
```
ISAC_LLM_PROVIDER → llm.provider
ISAC_LLM_API_KEY → llm.api_key
ISAC_DEBUG → debug
ISAC_LOG_LEVEL → log_level
ISAC_MEMORY_ENABLED → memory.enabled
```

### 3.3 多 Agent 配置

**配置层次** (后者覆盖前者):

1. 全局 `data/config.jsonc`
2. Agent 级 `data/agents/<agent_id>/config.jsonc` (只写覆盖项)
3. 环境变量 / CLI 参数

**全局配置新增**:

```jsonc
{
    // 控制面
    "control": {
        "enabled": true,
        "host": "127.0.0.1",            // 默认仅本机
        "port": 8765,
        "api_token": "...",             // Admin API / MCP Server 认证
        "mcp_server_enabled": false,
    },

    // 路由
    "router": {
        "rules_file": "data/routing.jsonc",
    },

    // 插件 Channel 级启用矩阵
    "plugins": {
        "channel_matrix": {
            "qq": {"deny": ["bash_tool"]},
        },
    },
}
```

**Agent 配置示例** (`data/agents/alice/config.jsonc`):

```jsonc
{
    "agent_id": "alice",
    "display_name": "爱丽丝",
    "trigger_words": ["爱丽丝", "@alice"],
    "persona": {"expression_style": {"humor": 0.8}},
    "gating": {"reply_necessity_threshold": 70},
    "plugins_allow": ["weather", "search"],
    "mcp_servers": ["filesystem"],
    "commands_allow": ["focus", "mute"],
}
```

**路由规则示例** (`data/routing.jsonc`):

```jsonc
{
    "bindings": [
        {"platform": "qq", "group_id": "123456", "agent_id": "alice"},
    ],
    "default_agents": {"qq": "bob", "telegram": "alice"},
}
```

**互联 Link 示例** (`data/links.jsonc`):

```jsonc
{
    "links": [
        {"from": "alice", "to": "bob", "direction": "both", "enabled": true},
    ],
}
```

---

## 四、协议定义

### 4.1 EventBus 事件类型

```python
from enum import Enum

class EventType(Enum):
    """ISAC 事件类型（由 EventBus 处理）"""

    # 生命周期
    ON_START = "on_start"                       # 系统启动
    ON_STOP = "on_stop"                         # 系统停止
    ON_SESSION_CREATE = "on_session_create"     # 会话创建
    ON_SESSION_CLOSE = "on_session_close"       # 会话关闭

    # 消息事件
    ON_MESSAGE_PRE = "on_message_pre"           # 消息预处理 (Intercept)
    ON_MESSAGE = "on_message"                   # 消息到达 (Intercept)
    POST_MESSAGE = "post_message"               # 消息处理完成 (Async)

    # 发送事件
    POST_SEND_PRE = "post_send_pre"             # 发送前预处理 (Intercept)
    POST_SEND = "post_send"                     # 发送完成 (Async)

    # 记忆事件
    ON_MEMORY_RETRIEVE = "on_memory_retrieve"   # 记忆检索
    ON_MEMORY_STORE = "on_memory_store"         # 记忆存储


# ──────────────────────────────────────────────────────────
# AgentHooks 事件 (Agent Loop 内部，与 EventBus 分离)
# 这些事件不经过 EventBus，直接在 Agent Loop 内部触发
# ──────────────────────────────────────────────────────────

class AgentHookPoint(Enum):
    """Agent Loop 内部钩子点（不经过 EventBus）"""
    PRE_LLM = "pre_llm"                         # LLM 调用前
    POST_LLM = "post_llm"                       # LLM 响应后
    PRE_TOOL = "pre_tool"                       # 工具调用前
    POST_TOOL = "post_tool"                     # 工具调用后
    COMPRESS = "compress"                       # 上下文压缩
    FINAL_RESPONSE = "final_response"           # 最终回复
```

### 4.2 WebSocket 协议 (内置 WebChat 适配器)

```python
# 客户端 → 服务端
{
    "type": "message",
    "data": {
        "content": "你好",
        "user_id": "user_001",
        "user_name": "小明",
        "platform": "webchat",
        "timestamp": 1721234567,
    }
}

# 服务端 → 客户端
{
    "type": "response",
    "data": {
        "msg_id": "msg_001",
        "content": "你好！有什么可以帮你的？",
        "timestamp": 1721234568,
    }
}

# 服务端 → 客户端 (流式)
{
    "type": "stream",
    "data": {
        "msg_id": "msg_001",
        "chunk": "你好！",
        "done": false,
    }
}
{
    "type": "stream",
    "data": {
        "msg_id": "msg_001",
        "chunk": "有什么可以帮你的？",
        "done": true,
    }
}
```

### 4.3 Inter-Agent 消息协议

总线内部消息格式（Webhook 可订阅 `inter_agent.sent` 事件）:

```json
{
    "type": "inter_agent",
    "from_agent": "alice",
    "to_agent": "bob",
    "msg_type": "request",
    "content": "用户问到了你擅长的领域...",
    "context": {"session_id": "sess_001", "summary": "..."},
    "timestamp": 1721234567
}
```

### 4.4 Admin REST API (控制面)

基础地址: `http://127.0.0.1:8765/api/v1`
认证: `Authorization: Bearer <control.api_token>`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /agents | 创建 Agent (body: AgentConfig) |
| GET | /agents | 列出 Agent |
| GET / PATCH / DELETE | /agents/{id} | 读取 / 改配置 / 销毁 |
| POST | /agents/{id}/start | 启动 |
| POST | /agents/{id}/stop | 停止 |
| GET / PUT | /routing/rules | 路由规则读写 (含默认 Agent) |
| GET / POST / DELETE | /links | 互联 Link 管理 |
| GET | /channels | 列出 Channel 连接 |
| POST / DELETE | /channels/{platform}/agents/{agent_id} | 绑定 / 解绑 |
| GET / PUT | /agents/{id}/plugins | 插件启用矩阵 |
| POST | /automation/trigger | 自动化触发器 (预留) |
| GET / POST / DELETE | /webhooks | Webhook 订阅管理 |

统一错误格式:

```json
{"error": {"code": "AGENT_NOT_FOUND", "message": "...", "retriable": false}}
```

Webhook 事件推送格式:

```json
{
    "event": "message.received",
    "timestamp": 1721234567,
    "data": {"agent_id": "alice", "platform": "qq", "...": "..."}
}
```

事件类型: `message.received` / `message.responded` / `agent.created` / `agent.stopped` / `inter_agent.sent`

### 4.5 ISAC MCP Server (控制面)

ISAC 可作为 MCP 服务端（`control.mcp_server_enabled: true`），让外部系统用 MCP 协议管理，与 Admin API 共用认证:

| 工具 | 说明 |
|------|------|
| agent_create | 创建 Agent |
| agent_update_config | 修改 Agent 参数 |
| agent_start / agent_stop | 生命周期 |
| channel_bind_agent / channel_unbind_agent | Channel ↔ Agent 绑定 |
| route_set_default | 设置平台默认 Agent |
| link_create / link_delete | 互联 Link 管理 |
| plugin_set_enabled | 插件启用矩阵 |
| message_send | 以某 Agent 身份发送消息 (自动化流程入口) |

---

## 五、错误处理规范

### 5.1 错误分类

| 类型 | 处理方式 | 示例 |
|------|---------|------|
| **平台连接错误** | 重连 + 日志 | Telegram API 超时 |
| **LLM 调用错误** | 重试 (3次) → 回退模型 → 降级回复 | OpenAI API 限流 |
| **记忆存储错误** | 日志记录，不阻塞消息流 | SQLite 写入失败 |
| **记忆检索错误** | 跳过本次注入，继续流程 | 向量搜索超时 |
| **工具执行错误** | 返回错误信息给 LLM | Bash 命令失败 |
| **插件错误** | 隔离插件，不影响其他插件 | 插件抛异常 |
| **门控错误** | 默认不回复 | 评分计算失败 |

### 5.2 错误处理模式

```python
# 1. LLM 调用: 重试 + 回退
async def chat_with_retry(self, **kwargs) -> LLMResponse:
    for attempt in range(3):
        try:
            return await self.provider.chat(**kwargs)
        except RateLimitError:
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            # 回退到备选模型
            return await self.fallback_provider.chat(**kwargs)

# 2. 记忆检索: 失败时返回空，不影响流程
async def safe_search(self, query: str) -> list[MemoryHit]:
    try:
        return await self.pipeline.search(query)
    except Exception as exc:
        logger.warning("记忆检索失败", error=str(exc))
        return []

# 3. 插件错误: 隔离
async def safe_call_plugin(self, plugin, method, *args):
    try:
        return await getattr(plugin, method)(*args)
    except Exception as exc:
        logger.error("插件执行失败", plugin=plugin.name, error=str(exc))
        # 不影响其他插件

# 4. Injector: 失败时返回空字符串
async def safe_build(self, context) -> str:
    try:
        return await self.build(context)
    except Exception as exc:
        logger.warning("Injector 失败", injector=self.key, error=str(exc))
        return ""
```

### 5.3 结构化错误

```python
# 位于 isac/core/exceptions.py

class ISACError(Exception):
    """ISAC 基础错误"""

    code: str = "ISAC_ERROR"
    retriable: bool = False

    def __init__(self, message: str, *, context: dict | None = None):
        super().__init__(message)
        self.message = message
        self.context = context

class PlatformError(ISACError):
    """平台连接错误"""
    code = "PLATFORM_ERROR"
    retriable = True

class LLMError(ISACError):
    """LLM 调用错误"""
    code = "LLM_ERROR"
    retriable = True

class MemoryError(ISACError):
    """记忆系统错误"""
    code = "MEMORY_ERROR"
    retriable = False

class ToolError(ISACError):
    """工具执行错误"""
    code = "TOOL_ERROR"
    retriable = False
```

---

## 六、专项规范索引

为避免主规范过长，以下施工细节独立成专项文档；实现对应模块前必须先阅读：

| 模块 | 必读文档 | 重点 |
|------|----------|------|
| 拟人化运行时 | [HUMANLIKE_RUNTIME.md](./HUMANLIKE_RUNTIME.md) | ConversationRuntime、wait、proactive、interrupt、context restore |
| 记忆系统 | [MEMORY_DESIGN.md](./MEMORY_DESIGN.md) | IdentityResolver、MemoryItem、keyword/hybrid/vector 模式、治理 |
| 路由与 Agent Mesh | [ROUTING_AND_AGENT_MESH.md](./ROUTING_AND_AGENT_MESH.md) | observer agent、handoff、Link ACL、上下文边界 |
| 插件兼容 | [PLUGIN_COMPATIBILITY.md](./PLUGIN_COMPATIBILITY.md) | 三格式加载、兼容矩阵、权限、测试插件集合 |
| 控制面 | [CONTROL_PLANE_SPEC.md](./CONTROL_PLANE_SPEC.md) | REST/MCP/Webhook schema、scope、audit、安全默认值 |

