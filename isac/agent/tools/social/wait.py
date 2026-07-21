"""wait 工具: 暂缓回复，等待更多消息。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class WaitTool(Tool):
    @property
    def name(self) -> str:
        return "wait"

    @property
    def description(self) -> str:
        return "暂时不回复，等待对方继续说"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"seconds": {"type": "integer", "description": "等待秒数", "default": 5}},
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 27): 设置会话等待状态 (与门控 idle_backoff 联动)。"""
        raise NotImplementedError("TODO(Day 27): 实现 wait")
