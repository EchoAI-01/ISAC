"""会话级并发控制 (SPECIFICATION.md 2.5)。

同一会话的消息串行处理，避免状态冲突；Agent 运行期间新消息排队。

K7: 引用计数 + 无 waiter 时回收锁对象, 防止长期运行 _locks 字典无界增长。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from isac.channel.model import ISACMessage
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class SessionLockManager:
    """会话级锁管理器 (K7: 引用计数回收)。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}  # session_id -> 等待中的数量
        self._agent_running: dict[str, bool] = {}
        self._queues: dict[str, list[ISACMessage]] = {}

    async def acquire(self, session_id: str) -> asyncio.Lock:
        """获取会话锁（不存在则创建）。K7: 跟踪 waiter 数, 0 时回收。"""
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        self._waiters[session_id] = self._waiters.get(session_id, 0) + 1
        return self._locks[session_id]

    def release(self, session_id: str) -> None:
        """释放锁引用, 无 waiter 时回收锁对象 (K7)。"""
        count = self._waiters.get(session_id, 0)
        if count <= 1:
            self._waiters.pop(session_id, None)
            # 只有锁不被持有时才能安全删除; 若被持有则保留等下一次 release
            lock = self._locks.get(session_id)
            if lock is not None and not lock.locked():
                self._locks.pop(session_id, None)
        else:
            self._waiters[session_id] = count - 1

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
        """
        lock = await self.acquire(message.session_id)
        try:
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
        finally:
            self.release(message.session_id)
