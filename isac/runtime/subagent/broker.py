"""J4 子任务结果回投 (SPECIFICATION.md 2.5.5)。

主 Agent 的默认 ToolResult 只包含 ``SubAgentResult``; 完整日志必须显式按 task_id 查询。

骨架状态: 内存 publish/get 就位; 异步通知 / 等待唤醒 / 跨进程投递留待 J4 实现节点。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isac.runtime.subagent.models import SubAgentResult


class SubAgentResultBroker:
    """子任务结果暂存与回投。"""

    def __init__(self) -> None:
        self._results: dict[str, SubAgentResult] = {}

    def publish(self, result: SubAgentResult) -> None:
        """登记一个子任务结果。"""
        self._results[result.task_id] = result

    def get(self, task_id: str) -> SubAgentResult | None:
        """按 task_id 取结果; 未就绪返回 None。"""
        return self._results.get(task_id)
