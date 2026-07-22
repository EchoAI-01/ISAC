"""send_emoji 工具: 发送表情 (ARCHITECTURE.md 3.5)。

经 services["channel_send"] 调用 Channel 适配器发送 emoji 分段。
若 channel_send 未注入 (无 Channel 场景), 返回友好错误而非 NotImplementedError,
避免把内部桩状态暴露给 LLM。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage


class SendEmojiTool(Tool):
    """在回复中发送表情包/emoji。"""

    @property
    def name(self) -> str:
        return "send_emoji"

    @property
    def description(self) -> str:
        return "发送一个表情 (emoji 或平台表情包)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"emoji": {"type": "string", "description": "表情内容"}},
            "required": ["emoji"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """经 channel_send 发送表情分段。"""
        emoji = str(context.args.get("emoji", "") or "").strip()
        if not emoji:
            return ToolResult(content="send_emoji 缺少 emoji 内容。", is_error=True)

        sender = context.services.get("channel_send")
        if sender is None:
            return ToolResult(content="当前未启用 Channel 发送能力，无法发送表情。", is_error=True)

        incoming = context.agent_context.current_message
        reply = _build_reply(incoming, emoji, segment_type="emoji")
        try:
            success = await sender(reply)
        except Exception as exc:
            return ToolResult(content=f"表情发送失败: {exc}", is_error=True)
        if not success:
            return ToolResult(content="表情发送未成功 (平台返回失败)。", is_error=True)
        return ToolResult(content=f"已发送表情: {emoji}")


def _build_reply(incoming: Any, content: str, *, segment_type: str) -> ISACMessage:
    """构造一条带 segment 的回复消息, 复用 incoming 的会话坐标。"""
    from isac.channel.model import ISACMessage, MessageSegment

    return ISACMessage(
        msg_id="",
        platform=getattr(incoming, "platform", ""),
        timestamp=0,
        user_id=getattr(incoming, "user_id", ""),
        user_name="",
        group_id=getattr(incoming, "group_id", None),
        content=content,
        segments=[MessageSegment(type=segment_type, data={"content": content})],
        reply_to=getattr(incoming, "msg_id", None) or None,
    )
