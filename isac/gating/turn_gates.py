"""触发门控 (ARCHITECTURE.md 3.7)。

按 pending 消息数决定是否达到触发阈值 (config.gating.trigger_threshold)。
"""

from __future__ import annotations


class TurnGates:
    """触发门控。"""

    def __init__(self, trigger_threshold: int = 3):
        self.trigger_threshold = trigger_threshold

    def reached(self, pending_count: int) -> bool:
        """积压消息数是否达到触发阈值。"""
        return pending_count >= self.trigger_threshold
