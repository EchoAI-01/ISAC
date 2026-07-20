"""话轮调度 (ARCHITECTURE.md 3.7)。

跟踪 bot 在会话中的发言频率，避免过度发言或长时间沉默。
注册 AgentHooks: POST_TOOL (更新话轮频率) / FINAL_RESPONSE (记录本轮回复)。
"""

from __future__ import annotations


class TurnScheduler:
    """话轮调度器。"""

    def __init__(self, max_ratio: float = 0.5):
        self.max_ratio = max_ratio  # bot 发言占窗口消息的最大比例
        self._recent_self_replies = 0
        self._recent_window_messages = 0

    def effective_frequency(self) -> float:
        """当前频率系数 (0.5~1.0)，发言越多系数越低。

        TODO(Day 17): 实现滑动窗口频率计算。
        """
        return 1.0

    def record_reply(self) -> None:
        """FINAL_RESPONSE hook: 记录本轮回复。"""
        self._recent_self_replies += 1

    def record_window_message(self) -> None:
        """记录窗口内新消息。"""
        self._recent_window_messages += 1
