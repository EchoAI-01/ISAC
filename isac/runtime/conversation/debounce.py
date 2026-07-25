"""DebounceWindow: 消息去抖合并骨架 (L2, HUMANLIKE_RUNTIME.md §4.2)。

[框架已搭建 / scaffolding] 静默窗口判定 + 连续消息合并的挂接点就位;真正的异步
延迟触发循环、按私聊/群聊分档的窗口时长、与 ConversationRuntime.should_trigger 的
联动留待 L2 实现节点 (见 TODO)。默认不接入主链路, 对现有 "每条即时处理" 零行为变化。
"""

from __future__ import annotations

import time


class DebounceWindow:
    """某会话的去抖窗口 (静默窗口内的连续消息合并为一次触发)。

    debounce_seconds<=0 时退化为 "不去抖" (每条立即可触发), 与现有行为一致。
    """

    def __init__(self, debounce_seconds: float = 0.0) -> None:
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        self._last_activity_at: float = 0.0

    def touch(self, now: float | None = None) -> None:
        """记录一次新消息活动, 刷新静默窗口起点。"""
        self._last_activity_at = now if now is not None else time.time()

    def is_settled(self, now: float | None = None) -> bool:
        """静默窗口是否已过 (可以触发一次合并处理)。

        TODO(L2): 由异步延迟触发循环调用 —— 在最后一条消息后 debounce_seconds
        内不触发, 期间到达的消息合并; 窗口结束后发起单次 TriggerSource.MESSAGE 话轮。
        骨架阶段: debounce_seconds<=0 恒 True (不去抖); >0 时按时间戳判定,
        但没有驱动它的循环, 故不改变现有触发行为。
        """
        if self.debounce_seconds <= 0.0:
            return True
        current = now if now is not None else time.time()
        return (current - self._last_activity_at) >= self.debounce_seconds
