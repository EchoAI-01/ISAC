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
from collections.abc import Callable
from typing import Any

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
    """门控系统门面。每个 AgentInstance 持有一个独立实例。

    TurnScheduler / IdleBackoffController 按 session_id 隔离持有 (复刻 FocusMode 的
    dict[session_id, ...] 模式)，避免同一 Agent 服务的多个会话共享发言频率/退避状态、
    互相干扰 (CODE_REVIEW_REPORT.md #6)。

    config 覆盖项 (AgentConfig.gating, ARCHITECTURE.md 3.7):
      - reply_necessity_threshold: int  覆盖 REPLY_NECESSITY_THRESHOLD
      - turn_scheduler.max_ratio / window_seconds
      - idle_backoff.base_seconds / cap_seconds
      - turn_gates.trigger_threshold
    未提供时使用各子系统的框架级默认值 (CODE_REVIEW_REPORT.md #8)。
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        reply_necessity: ReplyNecessityJudge | None = None,
        turn_scheduler: Callable[[], TurnScheduler] | None = None,
        turn_gates: TurnGates | None = None,
        idle_backoff: Callable[[], IdleBackoffController] | None = None,
    ):
        config = config or {}

        if reply_necessity is None:
            threshold = config.get("reply_necessity_threshold")
            reply_necessity = (
                ReplyNecessityJudge(threshold=int(threshold))
                if threshold is not None
                else ReplyNecessityJudge()
            )
        self.reply_necessity = reply_necessity

        if turn_scheduler is None:
            ts_cfg = config.get("turn_scheduler", {}) or {}
            turn_scheduler = lambda: TurnScheduler(  # noqa: E731
                max_ratio=float(ts_cfg.get("max_ratio", 0.5)),
                window_seconds=float(ts_cfg.get("window_seconds", 300.0)),
            )
        self._turn_scheduler_factory = turn_scheduler

        if turn_gates is None:
            tg_cfg = config.get("turn_gates", {}) or {}
            turn_gates = TurnGates(
                trigger_threshold=int(tg_cfg.get("trigger_threshold", 3))
            )
        self.turn_gates = turn_gates

        if idle_backoff is None:
            ib_cfg = config.get("idle_backoff", {}) or {}
            idle_backoff = lambda: IdleBackoffController(  # noqa: E731
                base_seconds=int(ib_cfg.get("base_seconds", 30)),
                cap_seconds=int(ib_cfg.get("cap_seconds", 300)),
            )
        self._idle_backoff_factory = idle_backoff

        self.focus_mode = FocusMode()
        self._turn_schedulers: dict[str, TurnScheduler] = {}
        self._idle_backoffs: dict[str, IdleBackoffController] = {}

    def get_turn_scheduler(self, session_id: str) -> TurnScheduler:
        """按 session_id 惰性创建/取回独立的 TurnScheduler。"""
        scheduler = self._turn_schedulers.get(session_id)
        if scheduler is None:
            scheduler = self._turn_scheduler_factory()
            self._turn_schedulers[session_id] = scheduler
        return scheduler

    def get_idle_backoff(self, session_id: str) -> IdleBackoffController:
        """按 session_id 惰性创建/取回独立的 IdleBackoffController。"""
        backoff = self._idle_backoffs.get(session_id)
        if backoff is None:
            backoff = self._idle_backoff_factory()
            self._idle_backoffs[session_id] = backoff
        return backoff

    async def evaluate(self, pending: list[ISACMessage], context: GatingContext) -> GateDecision:
        """评估门控决策，返回 TRIGGER / WAIT / DELAY(N秒)。"""
        session_id = context.session.session_id

        # 0. /mute 静音期内: 非 @ 触发一律 WAIT, 防止 Bot 主动发言。
        # 被 @ 仍然放行, 让用户能用 @bot /unmute 解锁 (CODE_REVIEW_REPORT.md #10)。
        muted_until = getattr(context.session, "muted_until", 0.0)
        if muted_until and not context.has_at:
            if time.monotonic() < muted_until:
                return GateDecision.wait()

        # 1. Focus Mode 激活时直接 TRIGGER
        if self.focus_mode.is_active(session_id):
            return GateDecision.trigger()

        # 2. 强制触发
        if context.has_at or (context.is_private and context.has_mention):
            return GateDecision.trigger()

        # 3. 回复必要性评分
        score = await self.reply_necessity.score(pending, context)
        if score < self.reply_necessity.threshold:
            return GateDecision.wait()

        # 4. 空闲退避 (按 session 隔离)
        idle_backoff = self.get_idle_backoff(session_id)
        if idle_backoff.should_delay(context.pending_count):
            return GateDecision.delay(idle_backoff.remaining_seconds)

        return GateDecision.trigger()
