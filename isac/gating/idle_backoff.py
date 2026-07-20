"""空闲退避 (ARCHITECTURE.md 3.7): 连续空闲 → 指数退避 (2^n 秒)。"""

from __future__ import annotations

import time


class IdleBackoffController:
    """空闲退避控制器。"""

    def __init__(self, base_seconds: int = 30, cap_seconds: int = 300):
        self.base_seconds = base_seconds
        self.cap_seconds = cap_seconds
        self._idle_streak = 0
        self._last_reply_at = 0.0

    @property
    def remaining_seconds(self) -> float:
        """当前退避剩余秒数。"""
        if self._idle_streak <= 0:
            return 0.0
        backoff = min(self.base_seconds * (2 ** (self._idle_streak - 1)), self.cap_seconds)
        elapsed = time.monotonic() - self._last_reply_at
        return max(0.0, backoff - elapsed)

    def should_delay(self, pending_count: int) -> bool:
        """是否处于退避期。

        TODO(Day 17): 结合 pending_count 调整 (积压多时缩短退避)。
        """
        return self.remaining_seconds > 0

    def record_reply(self) -> None:
        """记录一次回复，重置空闲计数。"""
        self._idle_streak = 0
        self._last_reply_at = time.monotonic()

    def record_idle(self) -> None:
        """记录一次空闲轮次，指数增长退避。"""
        self._idle_streak += 1
        self._last_reply_at = time.monotonic()
