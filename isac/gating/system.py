"""GatingSystem: 门控门面 (ARCHITECTURE.md 3.7)。

决策流程:
1. Focus Mode 激活 → TRIGGER
2. 强制触发 (has_at 或私聊带 mention) → TRIGGER
3. 回复必要性评分 < 阈值 → WAIT
4. 空闲退避中 → DELAY(N秒)
5. 否则 → TRIGGER
"""

from __future__ import annotations

import time

from isac.channel.model import ISACMessage
from isac.core.types import GatingContext
from isac.gating.idle_backoff import IdleBackoffController
from isac.gating.reply_necessity import ReplyNecessityJudge
from isac.gating.turn_gates import TurnGates
from isac.gating.turn_scheduler import TurnScheduler
from isac.gating.types import GateDecision


class FocusMode:
    """专注模式管理 (来自 MaiBot, ARCHITECTURE.md 3.7)。

    focus 状态下: Reply Necessity 基础分提升、Idle Backoff 被绕过、Turn Scheduler 阈值降低。
    """

    def __init__(self) -> None:
        self._active_until: dict[str, float] = {}  # session_id -> 过期时间 (monotonic)

    def is_active(self, session_id: str) -> bool:
        until = self._active_until.get(session_id, 0.0)
        return time.monotonic() < until

    def enter(self, session_id: str, duration: int = 300) -> None:
        self._active_until[session_id] = time.monotonic() + duration

    def exit(self, session_id: str) -> None:
        self._active_until.pop(session_id, None)


class GatingSystem:
    """门控系统门面。每个 AgentInstance 持有一个独立实例。"""

    def __init__(
        self,
        reply_necessity: ReplyNecessityJudge | None = None,
        turn_scheduler: TurnScheduler | None = None,
        turn_gates: TurnGates | None = None,
        idle_backoff: IdleBackoffController | None = None,
    ):
        self.reply_necessity = reply_necessity or ReplyNecessityJudge()
        self.turn_scheduler = turn_scheduler or TurnScheduler()
        self.turn_gates = turn_gates or TurnGates()
        self.idle_backoff = idle_backoff or IdleBackoffController()
        self.focus_mode = FocusMode()

    async def evaluate(self, pending: list[ISACMessage], context: GatingContext) -> GateDecision:
        """评估门控决策，返回 TRIGGER / WAIT / DELAY(N秒)。"""
        # 1. Focus Mode 激活时直接 TRIGGER
        if self.focus_mode.is_active(context.session.session_id):
            return GateDecision.trigger()

        # 2. 强制触发
        if context.has_at or (context.is_private and context.has_mention):
            return GateDecision.trigger()

        # 3. 回复必要性评分
        score = await self.reply_necessity.score(pending, context)
        if score < self.reply_necessity.threshold:
            return GateDecision.wait()

        # 4. 空闲退避
        if self.idle_backoff.should_delay(context.pending_count):
            return GateDecision.delay(self.idle_backoff.remaining_seconds)

        return GateDecision.trigger()
