"""会话级并发控制 (SPECIFICATION.md 2.5)。

同一会话的消息串行处理，避免状态冲突；Agent 运行期间新消息排队。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from isac.channel.model import ISACMessage
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class SessionLockManager:
    """会话级锁管理器。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._agent_running: dict[str, bool] = {}
        self._queues: dict[str, list[ISACMessage]] = {}

    async def acquire(self, session_id: str) -> asyncio.Lock:
        """获取会话锁（不存在则创建）。"""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    def is_agent_running(self, session_id: str) -> bool:
        """检查该会话是否有 Agent 在运行。"""
        return self._agent_running.get(session_id, False)

    def set_agent_running(self, session_id: str, running: bool) -> None:
        self._agent_running[session_id] = running

    async def handle_message(
        self,
        message: ISACMessage,
        handler: Callable[[ISACMessage], Awaitable[None]],
    ) -> None:
        """统一消息处理入口，保证同一会话串行。

        Agent 运行期间新消息排队等待 (MaiBot 做法)，处理完成后依次消费。
        TODO(Day 7): 排队消息的门控合并评估 (pending_count 累积触发)。
        """
        lock = await self.acquire(message.session_id)
        async with lock:
            if self.is_agent_running(message.session_id):
                self._queues.setdefault(message.session_id, []).append(message)
                logger.debug("Agent 运行中，消息已排队", session_id=message.session_id)
                return
            self.set_agent_running(message.session_id, True)
            try:
                await handler(message)
            finally:
                self.set_agent_running(message.session_id, False)
                queued = self._queues.pop(message.session_id, [])
                for queued_message in queued:
                    await handler(queued_message)
