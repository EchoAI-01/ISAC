"""read_file 工具: 读取文件 (限制在项目目录内)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取项目目录内的文件内容"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相对路径"}},
            "required": ["path"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 69): 路径白名单校验 (restricted 策略) + 读取。"""
        raise NotImplementedError("TODO(Day 69): 实现 read_file")
