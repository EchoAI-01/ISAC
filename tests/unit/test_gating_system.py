"""GatingSystem 会话级状态隔离测试 (CODE_REVIEW_REPORT.md #6)。

TurnScheduler / IdleBackoffController 曾经是 GatingSystem 的单例属性,
被同一 Agent 服务的所有会话共享, 导致一个会话的发言频率/退避状态污染另一个会话。
"""

from __future__ import annotations

from isac.gating.system import GatingSystem


class TestTurnSchedulerIsolation:
    def test_get_turn_scheduler_returns_same_instance_for_same_session(self) -> None:
        gating = GatingSystem()
        assert gating.get_turn_scheduler("sess_a") is gating.get_turn_scheduler("sess_a")

    def test_high_frequency_session_does_not_affect_other_session(self) -> None:
        gating = GatingSystem()
        scheduler_a = gating.get_turn_scheduler("sess_a")
        scheduler_b = gating.get_turn_scheduler("sess_b")

        for _ in range(10):
            scheduler_a.record_window_message()
            scheduler_a.record_reply()  # sess_a: Bot 每条都回复, 高发言占比

        assert scheduler_a.effective_frequency() < scheduler_b.effective_frequency()
        assert scheduler_b.recent_self_replies == 0
        assert scheduler_b.recent_window_messages == 0


class TestIdleBackoffIsolation:
    def test_get_idle_backoff_returns_same_instance_for_same_session(self) -> None:
        gating = GatingSystem()
        assert gating.get_idle_backoff("sess_a") is gating.get_idle_backoff("sess_a")

    def test_session_in_backoff_does_not_delay_other_session(self) -> None:
        gating = GatingSystem()
        backoff_a = gating.get_idle_backoff("sess_a")
        backoff_b = gating.get_idle_backoff("sess_b")

        backoff_a.record_reply()
        backoff_a.record_idle()
        backoff_a.record_idle()  # sess_a 连续空闲两轮 -> 进入指数退避

        assert backoff_a.remaining_seconds > 0
        assert backoff_b.remaining_seconds == 0
