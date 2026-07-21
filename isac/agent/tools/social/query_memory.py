"""query_memory 工具: 主动检索记忆。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class QueryMemoryTool(Tool):
    """让 Agent 主动查询长期记忆。"""

    @property
    def name(self) -> str:
        return "query_memory"

    @property
    def description(self) -> str:
        return "查询长期记忆 (只读)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询文本"},
                "top_k": {"type": "integer", "description": "返回条数", "default": 3},
            },
            "required": ["query"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(Day 26): 经 services["memory"] (MemoryRetrievalPipeline) 检索并格式化。

        失败时返回空结果而非异常 (SPECIFICATION.md 5.1: 记忆检索错误不阻塞)。
        """
        raise NotImplementedError("TODO(Day 26): 实现 query_memory")
