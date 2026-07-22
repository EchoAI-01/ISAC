"""view_forward_message 工具: 查看转发的合并消息内容 (ARCHITECTURE.md 3.5)。

经 services["channel_history"] 获取合并转发消息的详细内容; 未注入时返回友好错误。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class ViewForwardMessageTool(Tool):
    @property
    def name(self) -> str:
        return "view_forward_message"

    @property
    def description(self) -> str:
        return "查看合并转发消息的详细内容"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"forward_id": {"type": "string", "description": "转发消息 ID"}},
            "required": ["forward_id"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        forward_id = str(context.args.get("forward_id", "") or "").strip()
        if not forward_id:
            return ToolResult(content="view_forward_message 缺少 forward_id。", is_error=True)

        fetcher = context.services.get("channel_forward")
        if fetcher is None:
            return ToolResult(
                content="当前未启用合并转发消息读取能力，无法查看转发内容。",
                is_error=True,
            )

        try:
            messages = await fetcher(forward_id)
        except Exception as exc:
            return ToolResult(content=f"转发消息读取失败: {exc}", is_error=True)

        if not messages:
            return ToolResult(content=f"转发消息 {forward_id} 无内容或已失效。")

        lines = [f"【转发消息 {forward_id} ({len(messages)} 条)】"]
        for index, message in enumerate(messages, start=1):
            speaker = getattr(message, "user_name", "") or getattr(message, "user_id", "")
            content = str(getattr(message, "content", "") or "").strip()
            if content:
                lines.append(f"{index}. {speaker}: {content[:200]}")
        return ToolResult(content="\n".join(lines))
