"""会话级拟人化运行时 (L 节点, HUMANLIKE_RUNTIME.md)。

[框架已搭建 / scaffolding] 契约 + 状态机骨架 + per-session registry + 主动任务队列
就位,默认不接入主链路 (conversation.enabled=False),对现有消息处理零行为变化。
业务实现 (debounce / wait 闭环 / 主动调度 / 打断) 见 DEVELOPMENT_PLAN.md L1-L4。

CR2-Fix-3: 曾有一个孤立的 DebounceWindow 类与本模块并存, 从未被 ConversationRuntime
引用 (should_trigger 是 runtime.py 自己独立实现的等价逻辑), 属于死代码, 已删除。
"""

from __future__ import annotations

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
    "ForcedTurnState",
    "InterruptState",
    "ProactiveScheduler",
    "ProactiveTask",
    "ProactiveTaskQueue",
    "TriggerSource",
    "WaitEndReason",
    "WaitState",
]
