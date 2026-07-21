"""view_forward_message 工具: 查看转发的合并消息内容。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class ViewForwardMessageTool(Tool):
    @property
    def name(self) -> str:
        return "view_forward_message"

    @property
    def description(self) -> str:
        return "查看合并转发消息的详细内容"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"forward_id": {"type": "string", "description": "转发消息 ID"}},
            "required": ["forward_id"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 27): 经 Channel 适配器获取转发消息内容。"""
        raise NotImplementedError("TODO(Day 27): 实现 view_forward_message")
