"""GatingSystem 会话级状态隔离测试 (CODE_REVIEW_REPORT.md #6)。

TurnScheduler / IdleBackoffController 曾经是 GatingSystem 的单例属性,
被同一 Agent 服务的所有会话共享, 导致一个会话的发言频率/退避状态污染另一个会话。
"""

from __future__ import annotations

import pytest

from isac.channel.model import ISACMessage
from isac.core.types import GatingContext
from isac.gateway.models import Session
from isac.gating.system import GatingSystem
from isac.gating.types import GateKind


def _make_context(
    *,
    is_private: bool = False,
    has_at: bool = False,
    has_mention: bool = False,
    content: str = "你好",
) -> GatingContext:
    """构造最小 GatingContext 测试桩 (私聊/群聊/信号可配)。"""
    msg = ISACMessage(
        msg_id="m1",
        platform="webchat",
        timestamp=0,
        user_id="u1",
        user_name="u1",
        group_id=None if is_private else "g1",
        content=content,
    )
    session = Session(
        session_id="s1",
        user_id="u1",
        agent_id="a1",
        platform="webchat",
        group_id=None if is_private else "g1",
        is_group=not is_private,
    )
    return GatingContext(
        session=session,
        user_profile=None,
        current_message=msg,
        is_private=is_private,
        has_at=has_at,
        has_mention=has_mention,
    )


class TestForceTrigger:
    """T1: 私聊无条件强制触发 (修复开箱发消息永不回复)。"""

    @pytest.mark.asyncio
    async def test_private_chat_without_mention_triggers(self) -> None:
        """私聊"你好"无 @ 无 mention → TRIGGER (修复前: 40<80 静默 WAIT)。"""
        gating = GatingSystem()
        ctx = _make_context(is_private=True, has_at=False, has_mention=False)
        decision = await gating.evaluate([ctx.current_message], ctx)
        assert decision.kind == GateKind.TRIGGER

    @pytest.mark.asyncio
    async def test_private_chat_with_short_reaction_still_triggers(self) -> None:
        """私聊短反应"嗯"也触发 (短反应扣分在强制触发路径不生效, 可接受)。"""
        gating = GatingSystem()
        ctx = _make_context(is_private=True, content="嗯")
        decision = await gating.evaluate([ctx.current_message], ctx)
        assert decision.kind == GateKind.TRIGGER

    @pytest.mark.asyncio
    async def test_group_chat_without_at_or_mention_goes_to_score(self) -> None:
        """群聊无 @ 无 mention 不走强制触发, 落到 reply_necessity 评分。"""
        gating = GatingSystem()
        ctx = _make_context(is_private=False, has_at=False, has_mention=False)
        decision = await gating.evaluate([ctx.current_message], ctx)
        # 群聊普通消息 "你好" 评分 < 80 → WAIT (群聊行为不变)
        assert decision.kind == GateKind.WAIT

    @pytest.mark.asyncio
    async def test_group_chat_with_at_triggers(self) -> None:
        """群聊被 @ → TRIGGER (行为不变)。"""
        gating = GatingSystem()
        ctx = _make_context(is_private=False, has_at=True)
        decision = await gating.evaluate([ctx.current_message], ctx)
        assert decision.kind == GateKind.TRIGGER


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
