"""ConversationRuntime: 会话级拟人化运行时骨架 (HUMANLIKE_RUNTIME.md 三)。

[框架已搭建 / scaffolding] 契约 + 状态机 + 挂接点就位;真正的异步 debounce 触发、
wait 超时回填、主动任务调度、打断闭环留待 L1-L4 实现节点 (见各 TODO)。

每个 (agent_id, session_id) 一个独立实例,由 ConversationRuntimeRegistry 管理。
默认不接入主链路 (conversation.enabled=False),对现有 "每条消息即时处理" 零行为变化。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from isac.runtime.conversation.models import ConversationState, ForcedTurnState, WaitState
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage

logger = get_logger(__name__)


class ConversationRuntime:
    """某 Agent 在某会话中的拟人化运行时 (消息缓存 / 状态机 / 等待 / 打断)。"""

    def __init__(self, agent_id: str, session_id: str) -> None:
        self.agent_id = agent_id
        self.session_id = session_id
        self.state: ConversationState = ConversationState.IDLE
        self.message_cache: list[ISACMessage] = []
        self.last_processed_index: int = 0
        self.last_message_received_at: float = 0.0
        self.last_reply_at: float = 0.0
        self.pending_wait: WaitState | None = None
        self.forced_turn: ForcedTurnState | None = None

    def register_message(self, message: ISACMessage) -> None:
        """把新消息追加进缓存并更新时间戳 (debounce / 合并的输入)。"""
        self.message_cache.append(message)
        self.last_message_received_at = time.time()
        logger.debug(
            "会话缓存新消息",
            agent_id=self.agent_id,
            session_id=self.session_id,
            cached=len(self.message_cache),
        )

    def should_trigger(self, debounce_seconds: float = 0.0) -> bool:
        """判断是否已过静默窗口、可以触发一次处理。

        TODO(L2): 实现真正的 debounce —— 结合 last_message_received_at 与
        debounce_seconds 判断静默窗口是否结束,连续消息合并为一次触发。
        骨架阶段恒返回 True,不改变现有 "每条即时处理" 行为。
        """
        return True

    def transition_to(self, state: ConversationState) -> None:
        """状态机转移 (HUMANLIKE_RUNTIME.md §3.1)。"""
        logger.debug(
            "会话状态转移",
            agent_id=self.agent_id,
            session_id=self.session_id,
            from_state=self.state.value,
            to_state=state.value,
        )
        self.state = state

    def enter_wait(self, wait: WaitState) -> None:
        """进入等待态 (wait 工具调用触发)。"""
        self.pending_wait = wait
        self.transition_to(ConversationState.WAITING)

    def resolve_wait(self, reason: str = "") -> WaitState | None:
        """结束等待,返回被结束的 WaitState (无则 None)。

        TODO(L2): 由 timeout / message / proactive 触发,并向 AgentLoop 回填
        wait 工具结果 (说明实际等待时长)。骨架阶段仅做状态复位。
        """
        wait = self.pending_wait
        self.pending_wait = None
        if self.state is ConversationState.WAITING:
            self.transition_to(ConversationState.IDLE)
        return wait

    def request_interrupt(self) -> None:
        """请求打断当前规划 (新消息在 thinking 期间到达)。

        TODO(L4): 与 AgentContext.interrupt_requested 联动 —— 限制单轮打断次数、
        抑制被打断的旧回复、下一轮 Prompt 注入 "上一轮被新消息打断" 提示。
        """
        logger.debug("请求打断当前规划", agent_id=self.agent_id, session_id=self.session_id)

    def drain_new_messages(self) -> list[ISACMessage]:
        """取出自上次处理以来的新消息,并推进 last_processed_index。"""
        new = self.message_cache[self.last_processed_index :]
        self.last_processed_index = len(self.message_cache)
        return new
