"""send_image 工具: 发送图片 (需要 Image Gen API Key)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class SendImageTool(Tool):
    @property
    def name(self) -> str:
        return "send_image"

    @property
    def description(self) -> str:
        return "生成并发送一张图片"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "图片描述"}},
            "required": ["prompt"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 26): Image Gen Provider 生成 → Channel 发送。"""
        raise NotImplementedError("TODO(Day 26): 实现 send_image")
