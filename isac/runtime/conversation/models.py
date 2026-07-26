"""ConversationRuntime 数据契约 (HUMANLIKE_RUNTIME.md §三/§五)。

拟人化行为层的值对象: 会话状态、等待、主动任务、强制话轮。均为纯数据、不含行为;
行为在 ``runtime.py`` 的 ConversationRuntime。字段严格对齐专项设计文档,
供 L1-L4 实现节点直接填充,不在骨架阶段自创字段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ConversationState(StrEnum):
    """某会话的拟人化运行状态 (HUMANLIKE_RUNTIME.md §3.1 状态机)。"""

    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    WAITING = "waiting"
    STOPPED = "stopped"


class TriggerSource(StrEnum):
    """一次处理触发的来源 (HUMANLIKE_RUNTIME.md §4.1 触发源表)。

    debounce / 主动 / 打断决定用哪种来源发起话轮; L2-L4 落地时据此选择行为。
    """

    MESSAGE = "message"
    MENTION = "mention"
    PRIVATE = "private"
    PROACTIVE = "proactive"
    TIMEOUT = "timeout"
    HANDOFF = "handoff"


class WaitEndReason(StrEnum):
    """wait 结束的原因 (HUMANLIKE_RUNTIME.md §5.1)。

    等待由三条路径之一结束; 结束原因回填 wait 工具结果, 让 Agent 知道为何被唤醒。
    """

    MESSAGE = "message"  # 收到新消息
    TIMEOUT = "timeout"  # 到达 requested_seconds
    PROACTIVE = "proactive"  # 被主动任务唤醒


@dataclass
class WaitState:
    """Agent 主动等待状态 (wait 工具; HUMANLIKE_RUNTIME.md §5.1)。

    表示 Agent 选择暂时不说话,等待后续消息或超时再继续。
    """

    tool_call_id: str
    started_at: float
    requested_seconds: float | None = None
    reason: str = ""
    # L2: 等待结束时回填 (None = 仍在等待)。尾部默认字段, 不影响既有关键字构造。
    end_reason: WaitEndReason | None = None
    # L2: 实际等待秒数 (resolve_wait 时计算: time.time() - started_at)。尾部默认字段。
    actual_seconds: float = 0.0


@dataclass
class ProactiveTask:
    """结构化主动任务 (HUMANLIKE_RUNTIME.md §5.2)。

    主动行为必须有来源、意图、原因和优先级,不允许无来源随机说话。
    """

    task_id: str
    agent_id: str
    session_id: str
    source: str  # plugin | memory | schedule | agent | api
    intent: str
    reason: str
    priority: str = "normal"
    created_at: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class ForcedTurnState:
    """强制话轮: 一次绕过普通回复频率的发言 (超时 / 主动 / handoff 触发)。"""

    source: str  # timeout | proactive | handoff
    reason: str = ""
    created_at: float = 0.0


@dataclass
class InterruptState:
    """打断状态 (L4; HUMANLIKE_RUNTIME.md §5.3)。

    thinking 期间新消息到达时请求打断当前规划。记录本轮已打断次数以便限制,
    并保留原因供下一轮 Prompt 注入 "上一轮被新消息打断" 提示。
    行为 (抑制旧回复 / 单轮次数上限 / Prompt 提示) 由 L4 实现节点填充。
    """

    requested_at: float = 0.0
    reason: str = ""
    interrupt_count: int = 0  # 本轮累计打断次数, L4 用于限制连续打断
    superseded: bool = False  # 被打断的旧回复是否已抑制
