"""fetch_history 工具: 拉取聊天历史 (ARCHITECTURE.md 3.5)。

经 services["channel_history"] 拉取平台历史消息; 未注入时返回友好错误。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class FetchHistoryTool(Tool):
    @property
    def name(self) -> str:
        return "fetch_history"

    @property
    def description(self) -> str:
        return "拉取当前会话的聊天历史记录"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "条数", "default": 20}},
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """经 channel_history 拉取平台历史消息并格式化。"""
        fetcher = context.services.get("channel_history")
        if fetcher is None:
            return ToolResult(content="当前未启用历史拉取能力，无法获取聊天记录。", is_error=True)

        limit = max(1, int(context.args.get("limit", 20) or 20))
        incoming = context.agent_context.current_message
        try:
            messages = await fetcher(incoming, limit=limit)
        except Exception as exc:
            return ToolResult(content=f"聊天历史拉取失败: {exc}", is_error=True)

        if not messages:
            return ToolResult(content="没有可用的聊天历史。")

        lines = [f"【聊天历史 (最近 {len(messages)} 条)】"]
        for index, message in enumerate(messages, start=1):
            speaker = getattr(message, "user_name", "") or getattr(message, "user_id", "")
            content = str(getattr(message, "content", "") or "").strip()
            if content:
                lines.append(f"{index}. {speaker}: {content[:200]}")
        return ToolResult(content="\n".join(lines))
