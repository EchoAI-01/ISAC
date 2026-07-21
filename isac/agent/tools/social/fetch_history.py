"""fetch_history 工具: 拉取聊天历史。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class FetchHistoryTool(Tool):
    @property
    def name(self) -> str:
        return "fetch_history"

    @property
    def description(self) -> str:
        return "拉取当前会话的聊天历史记录"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数", "default": 20}},
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 27): 经 Channel 适配器拉取平台历史消息。"""
        raise NotImplementedError("TODO(Day 27): 实现 fetch_history")
