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
    # J1: 明细字段是 prompt_tokens/completion_tokens 的子集 (OpenAI 语义), 只用于
    # 可观测拆分与分档计价, 不参与 total_tokens 计算, 避免重复计数。
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0

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


# ── 任务进度 (SPECIFICATION.md 1.6) ───────────────────────────


@dataclass
class ProgressEvent:
    """Agent 任务阶段的结构化进度事实；不直接承载人格化文案。

    Agent Loop 只提交本事件，人格化渲染、频控、合并、脱敏与平台降级
    统一交给 ProgressReporter (isac/runtime/progress.py)。summary 必须
    是已脱敏的事实摘要，禁止包含 reasoning、密钥、原始工具参数或未清洗结果。
    """

    event_id: str
    task_id: str
    agent_id: str
    session_id: str
    # "planned" | "tool_started" | "tool_finished" | "tool_failed" | "completed" | "interrupted"
    stage: str
    tool_name: str | None = None
    summary: str = ""  # 已脱敏的事实摘要
    occurred_at: float = 0.0
    visible: bool = True
    metadata: dict = field(default_factory=dict)


# ── Context 层次 (ARCHITECTURE.md 3.4) ────────────────────────


@dataclass
class RuntimeContext:
    """贯穿一次消息处理的全局上下文（所有子 Context 的基类）"""

    session: Session
    user_profile: UserProfile | None
    current_message: ISACMessage
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
    # Q2 激活: 本轮(FINAL_RESPONSE 前的所有迭代)累计工具调用数, 供 MoodTracker
    # 等 FINAL_RESPONSE hook 读取"活跃度"信号——FINAL_RESPONSE 触发时 response
    # 本身恒无 tool_calls (那正是进final分支的条件), 不能从 response 上取。
    tool_calls_this_turn: int = 0
    reasoning_content: str = ""
    available_prompt_tokens: int = 8000
    streaming: bool = False
    on_chunk: Callable[[LLMChunk], Awaitable[None]] | None = None
    # C3: 流式响应中途失败后已推送过 chunk, fallback 只在 chunks=[] 时触发;
    # on_error 让调用方知道"已推送部分后失败", 可以选择向用户追加错误标记
    # 或回滚已推送的 chunks (取决于具体场景)。
    on_error: Callable[[Exception], Awaitable[None]] | None = None
    # 共享服务字典 (runtime/assembly 注入): gating/agent_manager/session_mgr 等
    # 让 Command 实现能访问 Agent 子系统 (CODE_REVIEW_REPORT.md #10)。
    services: dict[str, Any] = field(default_factory=dict)
    # 任务进度回调 (D9): Agent Loop 只提交 ProgressEvent，实际发送由 ProgressReporter 负责。
    # 默认 None 时进度报告关闭，主链路热路径零变化。返回值 (ProgressReporter.report
    # 返回 bool 表示是否实际发送) 由调用方按需读取, 故声明为 Awaitable[Any]。
    report_progress: Callable[[ProgressEvent], Awaitable[Any]] | None = None

    def should_compress(self) -> bool:
        """上下文是否过大需要压缩（触发 COMPRESS hook）。

        C4: 按 budget.remaining_tokens 间接判断, 接近溢出时触发压缩。
        粗略估算避免每次迭代都精确 token 化 (依赖 LLM Provider 才能
        tokenize, 开销大); 真实 prompt size 由 Provider 在 chat() 返回的
        usage.prompt_tokens 反馈, Budget.consume 已累计 used_tokens。
        """
        # budget 是 field(default_factory=Budget), 永远非 None
        # 20% 阈值: 剩余预算不足 20% 时触发 (留 20% 给最终回复 + 系统提示)
        return self.budget.remaining_tokens <= max(1, self.budget.max_tokens // 5)


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
