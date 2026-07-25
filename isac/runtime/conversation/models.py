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


@dataclass
class WaitState:
    """Agent 主动等待状态 (wait 工具; HUMANLIKE_RUNTIME.md §5.1)。

    表示 Agent 选择暂时不说话,等待后续消息或超时再继续。
    """

    tool_call_id: str
    started_at: float
    requested_seconds: float | None = None
    reason: str = ""


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
