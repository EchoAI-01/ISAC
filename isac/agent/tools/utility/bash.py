"""bash 工具: 执行 shell 命令 (默认禁用，DEVELOP.md 7.3)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class BashTool(Tool):
    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "执行 shell 命令 (需在配置中显式启用)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "命令"}},
            "required": ["command"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 69): 受限执行 + 超时 + 输出截断。"""
        raise NotImplementedError("TODO(Day 69): 实现 bash")
