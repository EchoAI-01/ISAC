"""主动任务生产者 (R2-2, HUMANLIKE_RUNTIME.md §5.2)。

ProactiveScheduler 只是"消费者"——后台循环从队列取任务并触发。此前生产侧没有
任何代码往队列 enqueue, 队列恒空, 整个主动任务子系统不可达。本模块提供第一个
真实生产者 IdleReengageProducer: 会话静默超过阈值时产出一个"主动关心"任务,
交给调度器 (经 authorize/冷却/唤醒回调) 触发。

默认关闭 (assembly 仅在 conversation.proactive.idle_reengage_seconds > 0 时接入),
保持主链路零行为变化。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from isac.runtime.conversation.models import ProactiveTask
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.conversation.registry import ConversationRuntimeRegistry

logger = get_logger(__name__)


class IdleReengageProducer:
    """空闲重连生产者: 会话静默超过 idle_seconds 时产出一个主动 re-engage 任务。

    调度器每个 poll 周期调用 ``producer(now)`` 收集待入队任务。去重策略保证一个静默
    窗口只主动打扰一次: 记录上次 re-engage 时该会话的 last_message_received_at,
    只有用户又发了新消息 (该时间戳前进) 才会重新武装, 避免对沉默用户反复轰炸。
    """

    def __init__(
        self,
        *,
        agent_id: str,
        registry: ConversationRuntimeRegistry,
        idle_seconds: float,
        priority: str = "low",
        caller_token: str = "",
    ) -> None:
        self._agent_id = agent_id
        self._registry = registry
        self._idle_seconds = max(1.0, float(idle_seconds))
        self._priority = priority
        self._caller_token = caller_token
        # session_id -> 上次 re-engage 时的 last_message_received_at (去重/重新武装依据)
        self._reengaged_marker: dict[str, float] = {}

    def __call__(self, now: float) -> list[ProactiveTask]:
        tasks: list[ProactiveTask] = []
        for session_id, runtime in self._registry.active_runtimes():
            last_activity = float(runtime.last_message_received_at or 0.0)
            if last_activity <= 0.0:
                continue  # 从未收到消息: 不主动打扰
            if (now - last_activity) < self._idle_seconds:
                continue  # 尚未静默够久
            if self._reengaged_marker.get(session_id, 0.0) >= last_activity:
                continue  # 本次静默窗口已 re-engage 过 (等新消息重置)
            self._reengaged_marker[session_id] = last_activity
            tasks.append(
                ProactiveTask(
                    task_id=f"reengage-{uuid.uuid4().hex[:12]}",
                    agent_id=self._agent_id,
                    session_id=session_id,
                    source="schedule",
                    intent="reengage",
                    reason="对话已静默一段时间, 主动关心一下",
                    priority=self._priority,
                    created_at=now,
                    caller_token=self._caller_token,
                )
            )
        if tasks:
            logger.debug("空闲重连生产者产出主动任务", agent_id=self._agent_id, count=len(tasks))
        return tasks
