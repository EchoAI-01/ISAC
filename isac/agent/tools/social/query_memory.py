"""query_memory 工具: 主动检索记忆。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import MemoryHit, ToolResult


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
        """经 services["memory"] 检索长期记忆并格式化。"""
        memory = context.services.get("memory")
        if memory is None:
            return ToolResult(content="未启用记忆服务，无法查询长期记忆。", is_error=True)

        query = str(context.args.get("query", "")).strip()
        if not query:
            return ToolResult(content="query_memory 缺少查询文本。", is_error=True)
        top_k = max(1, int(context.args.get("top_k", 3) or 3))

        try:
            hits = await memory.search(
                query,
                top_k=top_k,
                agent_id=getattr(context.agent_context.session, "agent_id", ""),
                user_id=getattr(context.agent_context.session, "user_id", ""),
                group_id=getattr(context.agent_context.session, "group_id", "") or "",
            )
        except Exception as exc:
            return ToolResult(content=f"记忆检索失败：{exc}", is_error=True)

        if not hits:
            return ToolResult(content="没有找到相关记忆。")
        return ToolResult(content=self._format_hits(hits[:top_k]))

    @staticmethod
    def _format_hits(hits: list[MemoryHit]) -> str:
        lines = ["【记忆查询结果】"]
        for index, hit in enumerate(hits, start=1):
            source = f" 来源: {hit.source}" if hit.source else ""
            lines.append(f"{index}. {hit.content}（score={hit.score:.3f}{source}）")
        return "\n".join(lines)
