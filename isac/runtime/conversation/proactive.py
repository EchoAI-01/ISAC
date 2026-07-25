"""ProactiveTaskQueue: 主动任务队列骨架 (HUMANLIKE_RUNTIME.md §5.2)。

[框架已搭建 / scaffolding] 入队 / 取出 + 长度查询就位;真正的按优先级调度、冷却与
频率边界、来源鉴权、唤醒对应会话留待 L3 实现节点 (见 TODO)。默认不启动后台调度,
零行为变化。
"""

from __future__ import annotations

from collections import deque

from isac.runtime.conversation.models import ProactiveTask
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ProactiveTaskQueue:
    """主动任务队列 (FIFO 骨架)。"""

    def __init__(self) -> None:
        self._queue: deque[ProactiveTask] = deque()

    def enqueue(self, task: ProactiveTask) -> None:
        """入队一个主动任务 (必须带 source / intent / reason,不允许无来源发言)。

        TODO(L3): 按 priority 排序 + 冷却 / 频率边界 + 来源鉴权,防止刷屏与滥用。
        """
        self._queue.append(task)
        logger.debug("主动任务入队", task_id=task.task_id, source=task.source, agent_id=task.agent_id)

    def poll(self) -> ProactiveTask | None:
        """取出下一个待执行主动任务;队列空返回 None。

        TODO(L3): 由调度器按冷却与优先级驱动,并唤醒对应会话的 ConversationRuntime。
        """
        if not self._queue:
            return None
        return self._queue.popleft()

    def __len__(self) -> int:
        return len(self._queue)
