"""web_search 工具: 网络搜索 (只读)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class WebSearchTool(Tool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "搜索网络信息"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索关键词"}},
            "required": ["query"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 69): 接入搜索 API。"""
        raise NotImplementedError("TODO(Day 69): 实现 web_search")
