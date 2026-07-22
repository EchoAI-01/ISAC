"""web_search 工具: 网络搜索 (只读)。

经 services["web_search"] 调用搜索后端; 未注入时返回友好错误。
"""

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
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "top_k": {"type": "integer", "description": "返回条数", "default": 5},
            },
            "required": ["query"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        search = context.services.get("web_search")
        if search is None:
            return ToolResult(content="未配置 web_search 后端, 无法搜索网络信息。", is_error=True)

        query = str(context.args.get("query", "") or "").strip()
        if not query:
            return ToolResult(content="web_search 缺少 query。", is_error=True)
        top_k = max(1, int(context.args.get("top_k", 5) or 5))

        try:
            results = await search(query, top_k=top_k)
        except Exception as exc:
            return ToolResult(content=f"搜索失败: {exc}", is_error=True)

        if not results:
            return ToolResult(content=f"未找到与「{query}」相关的网络结果。")

        lines = [f"【网络搜索结果 ({len(results)} 条)】"]
        for index, item in enumerate(results, start=1):
            title = str(item.get("title", "") or "")
            url = str(item.get("url", "") or "")
            snippet = str(item.get("snippet", "") or "").strip()
            lines.append(f"{index}. {title}\n   {url}\n   {snippet[:200]}")
        return ToolResult(content="\n".join(lines))
