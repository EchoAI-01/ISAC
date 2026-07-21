"""switch_chat 工具: 切换话题。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class SwitchChatTool(Tool):
    @property
    def name(self) -> str:
        return "switch_chat"

    @property
    def description(self) -> str:
        return "主动切换当前聊天话题"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "新话题"}},
            "required": ["topic"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 27): 更新会话话题状态并生成过渡语。"""
        raise NotImplementedError("TODO(Day 27): 实现 switch_chat")
