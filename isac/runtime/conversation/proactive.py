"""ProactiveTaskQueue: 主动任务队列 (L3, HUMANLIKE_RUNTIME.md §5.2)。

L3 实现: 按 priority 排序 (high > normal > low); 同优先 FIFO; poll 取最高优先。
enqueue 时按 priority 插入正确位置, 不阻塞主链路。
"""

from __future__ import annotations

from isac.runtime.conversation.models import ProactiveTask
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# priority → 排序键 (数字小的在前); 未知名按 normal 处理。
_PRIORITY_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}


def _priority_rank(task: ProactiveTask) -> int:
    """返回任务的 priority 排序键; 未知名视为 normal."""
    return _PRIORITY_RANK.get(task.priority, 1)


class ProactiveTaskQueue:
    """主动任务队列 (priority 排序, 同优先 FIFO)."""

    def __init__(self) -> None:
        # 用 list 而非 deque: priority 排序需要随机插入位置; enqueue 量级通常小, 线性查找足够。
        self._queue: list[ProactiveTask] = []

    def enqueue(self, task: ProactiveTask) -> None:
        """入队一个主动任务 (必须带 source/intent/reason, 按 priority 插入正确位置)。

        L3: priority 排序 high(0) > normal(1) > low(2); 同优先按入队顺序 FIFO。
        """
        # 找到第一个 rank > 当前 task rank 的位置, 插入之前 (保持同优先 FIFO)。
        rank = _priority_rank(task)
        insert_at = len(self._queue)
        for i, existing in enumerate(self._queue):
            if _priority_rank(existing) > rank:
                insert_at = i
                break
        self._queue.insert(insert_at, task)
        logger.debug(
            "主动任务入队",
            task_id=task.task_id,
            source=task.source,
            agent_id=task.agent_id,
            priority=task.priority,
            queue_len=len(self._queue),
        )

    def poll(self) -> ProactiveTask | None:
        """取出最高优先级任务 (同优先取最早入队的); 队列空返回 None。"""
        if not self._queue:
            return None
        return self._queue.pop(0)

    def __len__(self) -> int:
        return len(self._queue)
