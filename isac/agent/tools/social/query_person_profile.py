"""query_person_profile 工具: 查询人物画像 (只读)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class QueryPersonProfileTool(Tool):
    @property
    def name(self) -> str:
        return "query_person_profile"

    @property
    def description(self) -> str:
        return "查询某个用户的画像信息 (只读)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"user_name": {"type": "string", "description": "用户名"}},
            "required": ["user_name"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 27): 经 services["memory"] 查询 person_profiles。"""
        raise NotImplementedError("TODO(Day 27): 实现 query_person_profile")
