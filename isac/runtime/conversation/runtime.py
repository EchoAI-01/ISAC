"""ConversationRuntime: 会话级拟人化运行时 (HUMANLIKE_RUNTIME.md 三)。

L2 实现: should_trigger 真实 debounce 判定 + wait 闭环 (enter_wait 启动超时定时器,
resolve_wait 回填 end_reason/actual_seconds + 取消定时器, notify_new_message 在
WAITING 时结束 wait)。三条唤醒路径: message / timeout / proactive。
L4 实现: request_interrupt 单轮次数限制 + superseded 标记; clear_interrupt 进入
下一轮前重置; InterruptInjector 注入"上一轮被打断"提示。

默认不接入主链路 (conversation.enabled=False),对现有"每条消息即时处理"零行为变化。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from isac.runtime.conversation.models import (
    ConversationState,
    ForcedTurnState,
    InterruptState,
    WaitEndReason,
    WaitState,
)
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage

logger = get_logger(__name__)

# CR2-Fix-4: message_cache 软上限。register_message 是当前唯一在生产环境被
# manager 真实调用的写入路径 (drain_new_messages 从未被生产代码调用), 长会话下
# 若不设上限会无界增长。超出后丢弃最旧消息 (FIFO), 与 D9 的
# MAX_PROGRESS_REPORTERS_PER_AGENT 同思路。
_MAX_MESSAGE_CACHE = 200


class ConversationRuntime:
    """某 Agent 在某会话中的拟人化运行时 (消息缓存 / 状态机 / 等待 / 打断)。"""

    def __init__(self, agent_id: str, session_id: str, *, max_interrupts_per_turn: int = 1) -> None:
        self.agent_id = agent_id
        self.session_id = session_id
        self.state: ConversationState = ConversationState.IDLE
        self.message_cache: list[ISACMessage] = []
        self.last_processed_index: int = 0
        self.last_message_received_at: float = 0.0
        self.last_reply_at: float = 0.0
        self.pending_wait: WaitState | None = None
        self.forced_turn: ForcedTurnState | None = None
        # L4: 打断状态 (None = 本轮未被打断); max_interrupts_per_turn 限制单轮次数 (默认 1)。
        self.interrupt_state: InterruptState | None = None
        self.max_interrupts_per_turn: int = max(1, int(max_interrupts_per_turn))
        # L2: 等待 future 字典 (按 tool_call_id), wait 工具 await 之, resolve_wait 时 set_result。
        self._wait_futures: dict[str, asyncio.Future[WaitState]] = {}
        # L2: 超时定时器 task (按 tool_call_id), enter_wait 启动, resolve_wait 取消。
        self._timeout_tasks: dict[str, asyncio.Task[None]] = {}

    def register_message(self, message: ISACMessage) -> None:
        """把新消息追加进缓存并更新时间戳 (debounce / 合并的输入)。

        CR2-Fix-4: 超过 _MAX_MESSAGE_CACHE 时丢弃最旧消息, 并同步下修
        last_processed_index (被丢弃的消息里若含尚未 drain 的部分, 那些消息
        本就该被丢弃; max(0, ...) 保证索引不会变成负数)。
        """
        self.message_cache.append(message)
        if len(self.message_cache) > _MAX_MESSAGE_CACHE:
            overflow = len(self.message_cache) - _MAX_MESSAGE_CACHE
            del self.message_cache[:overflow]
            self.last_processed_index = max(0, self.last_processed_index - overflow)
        self.last_message_received_at = time.time()
        logger.debug(
            "会话缓存新消息",
            agent_id=self.agent_id,
            session_id=self.session_id,
            cached=len(self.message_cache),
        )

    def should_trigger(self, debounce_seconds: float = 0.0, *, now: float | None = None) -> bool:
        """判断是否已过静默窗口、可以触发一次处理。

        L2: debounce_seconds<=0 恒 True (兼容"每条即时处理"); 否则按
        last_message_received_at + debounce_seconds <= now 判定。now 参数便于测试。
        """
        if debounce_seconds <= 0.0:
            return True
        if self.last_message_received_at <= 0.0:
            return True
        current = now if now is not None else time.time()
        return (current - self.last_message_received_at) >= debounce_seconds

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

    async def enter_wait(self, wait: WaitState) -> None:
        """进入等待态 (wait 工具调用触发)。

        L2: 创建 future 让 wait 工具 await; requested_seconds 非空时启动超时定时器,
        到期触发 resolve_wait(TIMEOUT)。async 因为需要 running loop 才能创建 future/task。
        """
        self.pending_wait = wait
        self.transition_to(ConversationState.WAITING)
        loop = asyncio.get_running_loop()
        self._wait_futures[wait.tool_call_id] = loop.create_future()
        if wait.requested_seconds is not None and wait.requested_seconds > 0:
            self._timeout_tasks[wait.tool_call_id] = asyncio.create_task(self._wait_timeout(wait))
        logger.debug(
            "进入等待",
            agent_id=self.agent_id,
            session_id=self.session_id,
            tool_call_id=wait.tool_call_id,
            requested_seconds=wait.requested_seconds,
        )

    async def _wait_timeout(self, wait: WaitState) -> None:
        """超时定时器: sleep requested_seconds 后触发 resolve_wait(TIMEOUT)。

        被 resolve_wait 取消时静默退出 (CancelledError); 不阻塞主链路。
        """
        try:
            assert wait.requested_seconds is not None
            await asyncio.sleep(wait.requested_seconds)
        except asyncio.CancelledError:
            return
        self.resolve_wait(WaitEndReason.TIMEOUT)

    def resolve_wait(self, reason: WaitEndReason) -> WaitState | None:
        """结束等待,返回被结束的 WaitState (无则 None)。

        L2: 取消超时定时器; 回填 end_reason + actual_seconds (time.time() - started_at);
        set future result 唤醒 wait 工具; 状态机回 IDLE。
        """
        wait = self.pending_wait
        if wait is None:
            return None
        self.pending_wait = None
        # 取消超时定时器 (若存在)
        task = self._timeout_tasks.pop(wait.tool_call_id, None)
        if task is not None and not task.done():
            task.cancel()
        # 回填 + 状态复位
        wait.end_reason = reason
        wait.actual_seconds = max(0.0, time.time() - wait.started_at)
        if self.state is ConversationState.WAITING:
            self.transition_to(ConversationState.IDLE)
        # 唤醒 wait 工具
        future = self._wait_futures.pop(wait.tool_call_id, None)
        if future is not None and not future.done():
            future.set_result(wait)
        logger.debug(
            "等待结束",
            agent_id=self.agent_id,
            session_id=self.session_id,
            tool_call_id=wait.tool_call_id,
            end_reason=reason.value,
            actual_seconds=round(wait.actual_seconds, 3),
        )
        return wait

    async def await_wait(self, tool_call_id: str) -> WaitState:
        """wait 工具 await 此方法, 被 resolve_wait 唤醒后返回 WaitState。"""
        future = self._wait_futures.get(tool_call_id)
        if future is None:
            # 未注册 (理论上不会发生, wait 工具先 enter_wait 再 await): 返回哨兵 WaitState。
            return WaitState(tool_call_id=tool_call_id, started_at=time.time(), end_reason=WaitEndReason.MESSAGE)
        return await future

    def notify_new_message(self) -> None:
        """新消息到达时调用: 若处于 WAITING, 以 MESSAGE 原因结束等待。

        L2: manager 在 dispatch_message 时调用, 让 wait 工具被新消息唤醒。
        """
        if self.state is ConversationState.WAITING and self.pending_wait is not None:
            self.resolve_wait(WaitEndReason.MESSAGE)

    def request_interrupt(self, *, reason: str = "") -> bool:
        """请求打断当前规划 (新消息在 thinking 期间到达)。

        L4: 单轮打断次数上限 (max_interrupts_per_turn, 默认 1); 首次允许并置
        interrupt_state.superseded=True + interrupt_count=1; 后续同轮请求被拒绝。
        返回 True=允许打断, False=已达上限。AgentLoop 应在 thinking 后读
        interrupt_state.superseded 判定是否中断本轮。
        """
        if self.interrupt_state is None:
            self.interrupt_state = InterruptState(requested_at=time.time(), reason=reason)
        if self.interrupt_state.interrupt_count >= self.max_interrupts_per_turn:
            logger.info(
                "打断请求被拒 (单轮已达上限)",
                agent_id=self.agent_id,
                session_id=self.session_id,
                count=self.interrupt_state.interrupt_count,
                limit=self.max_interrupts_per_turn,
            )
            return False
        self.interrupt_state.interrupt_count += 1
        self.interrupt_state.superseded = True
        self.interrupt_state.reason = reason or self.interrupt_state.reason
        logger.debug(
            "请求打断当前规划",
            agent_id=self.agent_id,
            session_id=self.session_id,
            count=self.interrupt_state.interrupt_count,
            reason=reason,
        )
        return True

    def clear_interrupt(self) -> None:
        """本轮结束时清空打断状态 (供 AgentLoop 进入下一轮前调用)。

        L4: 清空后下一轮可再次被打断; InterruptInjector 注入提示后也应调此方法,
        避免重复注入。
        """
        if self.interrupt_state is not None:
            logger.debug(
                "清空打断状态",
                agent_id=self.agent_id,
                session_id=self.session_id,
                count=self.interrupt_state.interrupt_count,
            )
            self.interrupt_state = None

    def drain_new_messages(self) -> list[ISACMessage]:
        """取出自上次处理以来的新消息,并推进 last_processed_index。"""
        new = self.message_cache[self.last_processed_index :]
        self.last_processed_index = len(self.message_cache)
        return new
