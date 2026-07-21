"""send_emoji 工具: 发送表情。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class SendEmojiTool(Tool):
    """在回复中发送表情包/emoji。"""

    @property
    def name(self) -> str:
        return "send_emoji"

    @property
    def description(self) -> str:
        return "发送一个表情 (emoji 或平台表情包)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"emoji": {"type": "string", "description": "表情内容"}},
            "required": ["emoji"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 26): 经 Channel 适配器发送表情分段。"""
        raise NotImplementedError("TODO(Day 26): 实现 send_emoji")
