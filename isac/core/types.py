"""ISAC 核心类型定义。

数据模型契约见 SPECIFICATION.md 一；上下文层次见 ARCHITECTURE.md 3.4。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from isac.channel.model import ISACMessage
    from isac.gateway.models import Session, UserProfile


# ── 消息流状态 (SPECIFICATION.md 1.5) ─────────────────────────


class MessageStatus(Enum):
    """消息处理状态"""

    RECEIVED = "received"  # 已接收
    ROUTED = "routed"  # 已路由到会话/Agent
    GATED = "gated"  # 门控决策完成
    PROCESSING = "processing"  # Agent 处理中
    RESPONDING = "responding"  # 发送回复中
    COMPLETED = "completed"  # 完成
    DROPPED = "dropped"  # 被丢弃 (门控拒绝 / 路由无匹配)
    ERROR = "error"  # 处理出错


# ── LLM 相关 (SPECIFICATION.md 2.3) ───────────────────────────


@dataclass
class TokenUsage:
    """Token 使用情况。

    total_tokens 为 0 时，__post_init__ 自动按 prompt_tokens + completion_tokens 补齐，
    避免 Budget.consume() 累加 0 导致预算门控失效。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens


@dataclass
class ToolCall:
    """工具调用"""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果"""

    content: str
    is_error: bool = False


@dataclass
class LLMChunk:
    """流式响应的单个块"""

    delta_content: str = ""  # 增量文本
    delta_reasoning: str = ""  # 增量推理内容
    tool_call: ToolCall | None = None  # 完整的工具调用 (只在 finish_reason=tool_calls 时出现)
    finish_reason: str | None = None  # "stop" | "tool_calls" | "length"
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class LLMResponse:
    """LLM 响应"""

    content: str  # 文本内容
    reasoning: str = ""  # 推理内容 (如 o1/o3 模型)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""


# ── 记忆 (SPECIFICATION.md 1.4) ───────────────────────────────


@dataclass
class MemoryHit:
    """记忆检索结果"""

    id: str  # 记忆 ID
    content: str  # 记忆内容
    source: str  # 来源 (session_id)
    hit_type: str  # "episode" | "paragraph" | "person_fact"
    score: float  # 匹配分数
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None


# ── 预算 (SPECIFICATION.md 1.2) ───────────────────────────────


@dataclass
class Budget:
    """LLM 调用预算（同时跟踪迭代次数和 Token）"""

    max_iterations: int = 10  # 最大迭代次数
    max_tokens: int = 8000  # 最大 token 数
    remaining_iterations: int = 10  # 剩余迭代次数
    used_tokens: int = 0  # 已用 token 数

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


# ── Context 层次 (ARCHITECTURE.md 3.4) ────────────────────────


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

    budget: Budget = field(default_factory=Budget)
    iteration: int = 0
    interrupt_requested: bool = False
    reasoning_content: str = ""
    available_prompt_tokens: int = 8000
    streaming: bool = False
    on_chunk: Callable[[LLMChunk], Awaitable[None]] | None = None

    def should_compress(self) -> bool:
        """上下文是否过大需要压缩（触发 COMPRESS hook）。

        TODO(Day 14): 按 messages token 估算与 budget 阈值判定。
        """
        return False


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


# 便于外部构造测试桩的别名
ContextT = Any
