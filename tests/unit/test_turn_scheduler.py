"""TurnScheduler 滑动窗口频率与存在感计数测试 (D1 收尾, ARCHITECTURE.md 3.7)。"""

from __future__ import annotations

from isac.core.constants import GATING_FREQUENCY_MAX, GATING_FREQUENCY_MIN
from isac.gating.turn_scheduler import TurnScheduler


class TestEffectiveFrequency:
    def test_empty_window_returns_max(self):
        scheduler = TurnScheduler()
        assert scheduler.effective_frequency() == GATING_FREQUENCY_MAX
        assert scheduler.recent_self_replies == 0
        assert scheduler.recent_window_messages == 0

    def test_no_self_replies_returns_max(self):
        scheduler = TurnScheduler(max_ratio=0.5)
        for _ in range(10):
            scheduler.record_window_message()
        assert scheduler.effective_frequency() == GATING_FREQUENCY_MAX
        assert scheduler.recent_self_replies == 0
        assert scheduler.recent_window_messages == 10

    def test_self_ratio_at_max_clamps_to_min(self):
        scheduler = TurnScheduler(max_ratio=0.5)
        # 5 条他人 + 5 条自己 → self_ratio = 0.5 = max_ratio → MIN
        for _ in range(5):
            scheduler.record_window_message()
        for _ in range(5):
            scheduler.record_reply()
        assert scheduler.recent_self_replies == 5
        assert scheduler.recent_window_messages == 10
        assert scheduler.effective_frequency() == GATING_FREQUENCY_MIN

    def test_self_ratio_below_max_is_linear(self):
        scheduler = TurnScheduler(max_ratio=0.5)
        # 7 条他人 + 1 条自己 → ratio = 0.125 → MAX - span*(0.125/0.5) = MAX - span*0.25
        for _ in range(7):
            scheduler.record_window_message()
        scheduler.record_reply()
        span = GATING_FREQUENCY_MAX - GATING_FREQUENCY_MIN
        expected = GATING_FREQUENCY_MAX - span * 0.25
        got = scheduler.effective_frequency()
        assert abs(got - expected) < 1e-9
        assert GATING_FREQUENCY_MIN < got < GATING_FREQUENCY_MAX

    def test_self_ratio_exceeding_max_clamps_to_min(self):
        scheduler = TurnScheduler(max_ratio=0.5)
        # 全是自己发言 → ratio = 1.0 > max_ratio → MIN
        for _ in range(5):
            scheduler.record_reply()
        assert scheduler.effective_frequency() == GATING_FREQUENCY_MIN


class TestWindowExpiry:
    def test_expired_events_are_garbage_collected(self, monkeypatch):
        """过期事件被清理后, 计数与频率系数恢复到空窗状态。"""
        import time

        scheduler = TurnScheduler(window_seconds=10.0)
        # 模拟时间轴: 用 deque 真实时间戳, 通过 monkeypatch 让 _gc 看到未来时刻
        real_monotonic = time.monotonic
        # 先写入 5 条他人 + 5 条自己
        for _ in range(5):
            scheduler.record_window_message()
        for _ in range(5):
            scheduler.record_reply()
        assert scheduler.recent_window_messages == 10

        # 推进时间至窗口外
        elapsed = real_monotonic() + 100.0
        monkeypatch.setattr(
            "isac.gating.turn_scheduler.time.monotonic", lambda: elapsed
        )
        # 任何访问都会触发 _gc
        assert scheduler.recent_self_replies == 0
        assert scheduler.recent_window_messages == 0
        assert scheduler.effective_frequency() == GATING_FREQUENCY_MAX

    def test_capacity_protects_against_bursts(self):
        """超过 max_events 时丢弃最旧事件, 计数同步更新。"""
        scheduler = TurnScheduler(max_events=4)
        for _ in range(6):
            scheduler.record_window_message()
        # 容量 4, 全部他人消息, 频率系数仍为 MAX (无 self)
        assert scheduler.recent_window_messages == 4
        assert scheduler.recent_self_replies == 0
        assert scheduler.effective_frequency() == GATING_FREQUENCY_MAX
