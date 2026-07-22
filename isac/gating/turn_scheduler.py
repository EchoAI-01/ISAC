"""话轮调度 (ARCHITECTURE.md 3.7)。

跟踪 bot 在会话中的发言频率，避免过度发言或长时间沉默。
注册 AgentHooks: POST_TOOL (更新话轮频率) / FINAL_RESPONSE (记录本轮回复)。
"""

from __future__ import annotations

import time
from collections import deque

from isac.core.constants import GATING_FREQUENCY_MAX, GATING_FREQUENCY_MIN


class TurnScheduler:
    """话轮调度器。

    滑窗策略: 维护最近 window_seconds 秒内的 (timestamp, is_self) 事件序列，
    effective_frequency 基于 self_ratio = self_count / max(total_count, 1) 线性映射到
    [GATING_FREQUENCY_MIN, GATING_FREQUENCY_MAX]。发言占比越高，系数越低；占比为 0 时系数满。
    """

    def __init__(
        self,
        max_ratio: float = 0.5,
        window_seconds: float = 300.0,
        max_events: int = 200,
    ) -> None:
        self.max_ratio = max_ratio  # bot 发言占窗口消息的最大比例
        self.window_seconds = window_seconds
        self.max_events = max_events
        self._events: deque[tuple[float, bool]] = deque()  # (timestamp, is_self)
        # 计数缓存 (避免每次 evaluate 都全量扫描 deque)
        self._recent_self_replies = 0
        self._recent_window_messages = 0

    def effective_frequency(self) -> float:
        """当前频率系数 (GATING_FREQUENCY_MIN~GATING_FREQUENCY_MAX)。

        发言占比 self_ratio ∈ [0,1]:
          - self_ratio = 0 → 系数 = MAX (满频率)
          - self_ratio >= max_ratio → 系数 = MIN (最低频率)
        线性插值，超出 max_ratio 的部分钳制到 MIN。
        """
        self._gc()
        total = self._recent_window_messages
        if total <= 0:
            return GATING_FREQUENCY_MAX
        self_ratio = min(self._recent_self_replies / total, 1.0)
        if self_ratio >= self.max_ratio:
            return GATING_FREQUENCY_MIN
        # 0 → MAX, max_ratio → MIN
        span = GATING_FREQUENCY_MAX - GATING_FREQUENCY_MIN
        return GATING_FREQUENCY_MAX - span * (self_ratio / self.max_ratio)

    @property
    def recent_self_replies(self) -> int:
        """窗口内本 Agent 回复数。"""
        self._gc()
        return self._recent_self_replies

    @property
    def recent_window_messages(self) -> int:
        """窗口内总消息数 (含本 Agent 回复)。"""
        self._gc()
        return self._recent_window_messages

    def record_reply(self) -> None:
        """FINAL_RESPONSE hook: 记录本轮回复。"""
        self._push(time.monotonic(), is_self=True)

    def record_window_message(self) -> None:
        """记录窗口内一条新消息 (通常是他人消息)。"""
        self._push(time.monotonic(), is_self=False)

    def _push(self, timestamp: float, is_self: bool) -> None:
        self._events.append((timestamp, is_self))
        if is_self:
            self._recent_self_replies += 1
        self._recent_window_messages += 1
        # 容量保护: 事件过多时丢弃最旧的 (即便未过期)
        while len(self._events) > self.max_events:
            _, old_is_self = self._events.popleft()
            if old_is_self:
                self._recent_self_replies -= 1
            self._recent_window_messages -= 1

    def _gc(self) -> None:
        """清理窗口外过期事件。"""
        cutoff = time.monotonic() - self.window_seconds
        while self._events:
            timestamp, is_self = self._events[0]
            if timestamp > cutoff:
                break
            self._events.popleft()
            if is_self:
                self._recent_self_replies -= 1
            self._recent_window_messages -= 1
