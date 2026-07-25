"""会话级拟人化运行时 (L 节点, HUMANLIKE_RUNTIME.md)。

[框架已搭建 / scaffolding] 契约 + 状态机骨架 + per-session registry + 主动任务队列
就位,默认不接入主链路 (conversation.enabled=False),对现有消息处理零行为变化。
业务实现 (debounce / wait 闭环 / 主动调度 / 打断) 见 DEVELOPMENT_PLAN.md L1-L4。
"""

from __future__ import annotations

from isac.runtime.conversation.debounce import DebounceWindow
from isac.runtime.conversation.models import (
    ConversationState,
    ForcedTurnState,
    InterruptState,
    ProactiveTask,
    TriggerSource,
    WaitEndReason,
    WaitState,
)
from isac.runtime.conversation.proactive import ProactiveTaskQueue
from isac.runtime.conversation.recovery import ConversationSnapshot, ConversationStateStore
from isac.runtime.conversation.registry import ConversationRuntimeRegistry
from isac.runtime.conversation.runtime import ConversationRuntime
from isac.runtime.conversation.scheduler import ProactiveScheduler

__all__ = [
    "ConversationRuntime",
    "ConversationRuntimeRegistry",
    "ConversationSnapshot",
    "ConversationState",
    "ConversationStateStore",
    "DebounceWindow",
    "ForcedTurnState",
    "InterruptState",
    "ProactiveScheduler",
    "ProactiveTask",
    "ProactiveTaskQueue",
    "TriggerSource",
    "WaitEndReason",
    "WaitState",
]
