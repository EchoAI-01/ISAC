"""write_file 工具: 写入文件 (限制在项目目录内)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class WriteFileTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "写入项目目录内的文件"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对路径"},
                "content": {"type": "string", "description": "文件内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 69): 路径白名单校验 (restricted 策略) + 写入。"""
        raise NotImplementedError("TODO(Day 69): 实现 write_file")
