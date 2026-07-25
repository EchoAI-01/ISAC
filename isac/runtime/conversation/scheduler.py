"""ProactiveScheduler: 主动任务调度骨架 (L3, HUMANLIKE_RUNTIME.md §5.2)。

[框架已搭建 / scaffolding] 从 ProactiveTaskQueue 取任务的调度挂接点就位;真正的按
优先级排序、冷却与频率边界、来源鉴权、唤醒对应会话发起强制话轮留待 L3 实现节点
(见 TODO)。默认不启动后台调度, 对主链路零行为变化。
"""

from __future__ import annotations

from isac.runtime.conversation.models import ForcedTurnState, ProactiveTask, TriggerSource
from isac.runtime.conversation.proactive import ProactiveTaskQueue
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ProactiveScheduler:
    """主动任务调度器骨架 (驱动 ProactiveTaskQueue)。

    每个 Agent 一个, 由 L3 的后台循环按冷却/频率驱动; 骨架阶段仅提供判定与
    转换的纯函数式挂接点, 不含后台任务。
    """

    def __init__(self, queue: ProactiveTaskQueue | None = None, *, min_interval_seconds: float = 0.0) -> None:
        # 用 is None 判定而非 `queue or ...`: 空队列 __len__==0 为 falsy, or 会误建新队列。
        self.queue = queue if queue is not None else ProactiveTaskQueue()
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._last_fired_at: float = 0.0

    def may_fire(self, now: float) -> bool:
        """是否已过冷却窗口、允许再触发一个主动任务。

        TODO(L3): 结合 effective_frequency (存在感/关系/专注度) 与 min_interval_seconds
        判定; 骨架阶段仅按 min_interval_seconds 判定, 无后台循环驱动故不产生主动发言。
        """
        if self.min_interval_seconds <= 0.0:
            return True
        return (now - self._last_fired_at) >= self.min_interval_seconds

    def authorize(self, task: ProactiveTask) -> bool:
        """校验主动任务来源合法 (禁止无来源随机发言)。

        TODO(L3): 按 source (plugin/memory/schedule/agent/api) 做来源鉴权与配额;
        骨架阶段仅要求 source/intent/reason 非空。
        """
        return bool(task.source and task.intent and task.reason)

    def to_forced_turn(self, task: ProactiveTask) -> ForcedTurnState:
        """把一个主动任务转成强制话轮状态 (供 ConversationRuntime 发起)。

        TODO(L3): 触发时更新 _last_fired_at 并唤醒对应会话的 ConversationRuntime。
        """
        return ForcedTurnState(source=TriggerSource.PROACTIVE.value, reason=task.reason)
