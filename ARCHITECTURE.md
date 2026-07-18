# ISAC — 生产级架构设计文档

> Intelligent Social AI Companion v2.1
> 状态: 生产就绪设计

---

## 目录

- [一、设计原则](#一设计原则)
- [二、系统架构](#二系统架构)
- [三、核心组件设计](#三核心组件设计)
- [四、消息生命周期](#四消息生命周期)
- [五、目录结构](#五目录结构)
- [六、设计决策记录](#六设计决策记录)
- [七、非功能性需求](#七非功能性需求)

---

## 一、设计原则

| 原则 | 说明 |
|------|------|
| **拟人即 Prompt** | 拟人能力通过 System Prompt 注入实现，不是代码变换 |
| **单点集成** | 所有子系统通过 `SystemPromptBuilder` 和 `AgentHooks` 两个枢纽参与 Agent 循环 |
| **门控先于 Agent** | 是否回复、何时回复的决定先于 Agent 调用 |
| **记忆是检索流水线** | 嵌入模型 + 双路径搜索 + 重排序，不是简单 K-V |
| **事件驱动** | 消息处理通过 EventBus 双层事件 (Intercept + Async) 解耦 |
| **兼容 AstrBot** | 不发明新插件协议，桥接 AstrBot Star 系统 |
| **简洁优先** | 不引入不必要的外部依赖，单机可运行 |

---

## 二、系统架构

```
┌───────────────────────────────────────────────────────────────────────────┐
│                         ISAC System Architecture                           │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│   ┌────────────────────── CHANNEL LAYER ────────────────────────────┐    │
│   │                                                                 │    │
│   │   QQ  Telegram  Discord  WeChat  Slack  KOOK  WebSocket ...   │    │
│   │          AstrBot Platform Adapters (18+)                       │    │
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
│   ┌─────────────────── GATING SYSTEM (门控) ──────────────────────┐    │
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
│   │      while budget.remaining > 0:                             │    │
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
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌────────────────── PLUGIN SYSTEM ────────────────────────────┐    │
│   │                                                               │    │
│   │  ┌───────────────────────────────────────────────────────┐  │    │
│   │  │  AstrBot Compatibility Layer                          │  │    │
│   │  │  Star / Context / EventType / FunctionTool            │  │    │
│   │  └───────────────────────────────────────────────────────┘  │    │
│   │  ┌───────────────────────────────────────────────────────┐  │    │
│   │  │  ISAC Native Plugin SDK                               │  │    │
│   │  │  Hooks / Injectors / Tools / MCP                      │  │    │
│   │  └───────────────────────────────────────────────────────┘  │    │
│   └───────────────────────────┬─────────────────────────────────────┘    │
│                               │                                          │
│   ┌────────────────── PROVIDER LAYER ───────────────────────────┐    │
│   │                                                               │    │
│   │  LLM / Embedding / Reranker / STT / TTS / ImageGen          │    │
│   │  来源: AstrBot (42 providers) + opencode LLM                │    │
│   │                                                               │    │
│   └───────────────────────────────────────────────────────────┘    │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心组件设计

### 3.1 System Prompt Builder — 所有子系统的集成枢纽

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


@dataclass
class GatingContext(RuntimeContext):
    """门控决策上下文"""
    pending_count: int = 0
    has_at: bool = False
    has_mention: bool = False
    is_private: bool = False
    idle_seconds: float = 0.0
    effective_frequency: float = 1.0
    recent_self_replies: int = 0
    recent_window_messages: int = 0
    focus_active: bool = False  # Focus Mode 是否激活


class PromptInjector(ABC):
    """Prompt 注入器抽象基类。所有注入器必须继承此类。"""

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

### 3.2 Agent Loop — 开放注入点

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
    FINAL_RESPONSE = "final"      # 最终回复前


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

        while context.budget.remaining > 0:
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

                    # POST_TOOL: 触发记忆更新
                    await self.hooks.fire(AgentHookPoint.POST_TOOL, tc, result, context)
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
            prompt_tokens=chunks[-1].usage.prompt_tokens if chunks else 0,
            completion_tokens=chunks[-1].usage.completion_tokens if chunks else 0,
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
| `COMPRESS` | MidTermMemoryManager | 触发中期记忆压缩 |
| `FINAL_RESPONSE` | TurnScheduler | 记录本轮回复 |
| `FINAL_RESPONSE` | BehaviorLearner | 从回复中学习行为模式 |

---

### 3.3 Memory System — 检索流水线

**核心职责**: 跨会话的记忆存储、检索、注入。

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
CREATE INDEX idx_episodes_user ON episodes(user_id);
CREATE INDEX idx_episodes_time ON episodes(created_at);

CREATE VIRTUAL TABLE episodes_fts USING fts5(
    content, summary, topics, participants,
    content=episodes, content_rowid=rowid
);

CREATE TABLE person_profiles (
    person_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile_text TEXT,
    traits TEXT,            -- JSON array
    relationship_depth REAL DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    first_seen INTEGER,
    last_seen INTEGER,
    embedding_hash TEXT     -- 用于向量关联
);

CREATE TABLE jargon_entries (
    word TEXT PRIMARY KEY,
    meaning TEXT NOT NULL,
    context TEXT,
    usage_count INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);

-- VectorStore (sqlite-vec)

CREATE VIRTUAL TABLE vectors USING vec0(
    id TEXT PRIMARY KEY,
    embedding FLOAT[1024]    -- 维度可配置
);
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

### 3.4 Gating System — 门控

**核心职责**: 决定"要不要说话、什么时候说"。

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
        if context.has_at or context.is_private_with_mention:
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

### 3.5 Plugin System — AstrBot 兼容 + 原生 SDK

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

import importlib
import sys

class AstrBotImportFinder:
    """拦截 astrbot.* 的 import"""

    # 兼容层覆盖的 astrbot 模块清单
    MAPPING = {
        "astrbot.api.star": "isac.plugin.compatibility.star",
        "astrbot.api.event": "isac.plugin.compatibility.events",
        "astrbot.api.provider": "isac.plugin.compatibility.provider",
        "astrbot.api.platform": "isac.plugin.compatibility.platform",
    }

    def find_module(self, name: str, path=None):
        if name.startswith("astrbot."):
            if name in self.MAPPING:
                return AstrBotModuleLoader(self.MAPPING[name])
            # 未映射的 astrbot 模块 → 抛出 ImportError
            # 开发者需要为深层 import 添加映射
            raise ImportError(
                f"不支持的 astrbot 模块: {name}。"
                f"兼容层仅覆盖: {list(self.MAPPING.keys())}"
            )
        return None

class AstrBotModuleLoader:
    def __init__(self, target_module: str):
        self.target = target_module

    def load_module(self, name: str):
        module = importlib.import_module(self.target)
        sys.modules[name] = module
        return module

# 安装沙箱 (在插件加载前)
sys.meta_path.insert(0, AstrBotImportFinder())
```

**局限性**: 深层 import (如 `from astrbot.core.xxx import yyy`) 需要为每个子模块建立映射。建议 P2 阶段先实现常用模块的映射，其他按需扩展。

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
        "0.9.0": migrate_from_0_9_to_1_0,
        "1.0.0": migrate_from_1_0_to_1_1,
    }

    def migrate(self, config: dict) -> dict:
        """从当前版本迁移到最新版本"""
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
[SessionManager]  查找/创建 Session                          │
    │  跨平台用户识别 (UserMapper)                            │
    │  加载 UserProfile                                       │
    │                                                        │
    ▼                                                        │
[🚪 GatingSystem]  ⬅ 是否进入 Agent?                        │
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
│   │   └── constants.py            # 常量
│   │
│   ├── locales/                    # 多语言支持 (i18n)
│   │   ├── __init__.py             # load_text() 工具函数
│   │   ├── zh_CN.py                # 中文 (默认)
│   │   ├── en_US.py                # 英文
│   │   └── ja_JP.py                # 日文
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
│   │   └── models.py               # Session/Profile 数据模型
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
│   │   ├── injector.py             # PromptInjector 基类
│   │   ├── injectors/              # 内置注入器
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── attention_drift.py
│   │   │   ├── expression_style.py
│   │   │   ├── mood.py
│   │   │   └── skill_selector.py
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
│   │   └── mood.py                 # 情绪状态
│   │
│   ├── plugin/                     # Plugin System
│   │   ├── __init__.py
│   │   ├── compatibility/          # AstrBot 兼容层
│   │   │   ├── __init__.py
│   │   │   ├── star.py             # Star 基类
│   │   │   ├── context.py          # Context API 模拟
│   │   │   ├── events.py           # EventType 映射
│   │   │   ├── tools.py            # FunctionTool 桥接
│   │   │   └── sandbox.py          # Import 重定向
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
│   │   ├── llm/                    # LLM Providers
│   │   │   ├── __init__.py
│   │   │   ├── openai.py
│   │   │   ├── anthropic.py
│   │   │   ├── google.py
│   │   │   └── ...                 # 更多
│   │   ├── embed/                  # Embedding Providers
│   │   ├── rerank/                 # Reranking Providers
│   │   └── stt_tts/                # STT/TTS Providers
│   │
│   └── utils/                      # 工具
│       ├── __init__.py
│       ├── logger.py               # 日志
│       ├── config.py               # 配置加载
│       └── helpers.py
│
├── plugins/                        # 第三方插件目录
│   ├── .gitkeep
│   └── README.md
│
├── data/                           # 运行数据 (gitignored)
│   ├── config.jsonc
│   ├── memory/
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

---

## 八、非功能性需求

| 维度 | 要求 |
|------|------|
| **性能** | 消息处理延迟 < 5s (不含 LLM 推理) |
| **并发** | 支持多平台同时连接，单实例 100+ 并发会话 |
| **可靠性** | 单会话故障不影响其他会话；记忆写入失败不阻塞消息流 |
| **可扩展性** | 新平台适配器只需实现 `PlatformAdapter` 接口 |
| **可维护性** | 每个子系统可独立测试；模块间通过明确接口通信 |
| **安全性** | 插件沙箱隔离；敏感信息 (API Key) 加密存储 |
| **可观测性** | 结构化日志 (structlog)；关键事件带上下文信息 |
