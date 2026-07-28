"""会话级并发控制 (SPECIFICATION.md 2.5)。

同一会话的消息串行处理，避免状态冲突 (生产路径见 main._process_locked:
acquire → async with lock → release)。

K7: 引用计数 + 无 waiter 时回收锁对象, 防止长期运行 _locks 字典无界增长。
"""

from __future__ import annotations

import asyncio


class SessionLockManager:
    """会话级锁管理器 (K7: 引用计数回收)。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}  # session_id -> 等待中的数量

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
