"""task 工具: 子 Agent 委派 (限制递归深度和预算)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class TaskTool(Tool):
    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return "将子任务委派给一个子 Agent 执行"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "子任务描述"},
            },
            "required": ["task"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 70): 子 Agent Loop + 独立预算 + 递归深度限制。"""
        raise NotImplementedError("TODO(Day 70): 实现 task 子 Agent 委派")
