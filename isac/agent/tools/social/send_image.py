"""send_image 工具: 发送图片 (ARCHITECTURE.md 3.5)。

生成图片需要 Image Gen Provider; 当前 MVP 阶段, 若 services["image_gen"] 未注入,
返回友好错误, 而非抛 NotImplementedError 把桩状态暴露给 LLM。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage


class SendImageTool(Tool):
    @property
    def name(self) -> str:
        return "send_image"

    @property
    def description(self) -> str:
        return "生成并发送一张图片"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "图片描述"}},
            "required": ["prompt"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """image_gen 生成 → channel_send 发送。"""
        prompt = str(context.args.get("prompt", "") or "").strip()
        if not prompt:
            return ToolResult(content="send_image 缺少 prompt。", is_error=True)

        sender = context.services.get("channel_send")
        image_gen = context.services.get("image_gen")
        if sender is None:
            return ToolResult(content="当前未启用 Channel 发送能力，无法发送图片。", is_error=True)
        if image_gen is None:
            return ToolResult(
                content="未配置图片生成 Provider (image_gen), 无法生成图片。",
                is_error=True,
            )

        try:
            image_data = await image_gen.generate(prompt)
        except Exception as exc:
            return ToolResult(content=f"图片生成失败: {exc}", is_error=True)
        if not image_data:
            return ToolResult(content="图片生成返回空结果。", is_error=True)

        incoming = context.agent_context.current_message
        reply = _build_image_reply(incoming, image_data)
        try:
            success = await sender(reply)
        except Exception as exc:
            return ToolResult(content=f"图片发送失败: {exc}", is_error=True)
        if not success:
            return ToolResult(content="图片发送未成功 (平台返回失败)。", is_error=True)
        return ToolResult(content=f"已发送图片 (prompt={prompt[:40]})")


def _build_image_reply(incoming: Any, image_data: str) -> ISACMessage:
    from isac.channel.model import ISACMessage, MessageSegment

    return ISACMessage(
        msg_id="",
        platform=getattr(incoming, "platform", ""),
        timestamp=0,
        user_id=getattr(incoming, "user_id", ""),
        user_name="",
        group_id=getattr(incoming, "group_id", None),
        content="[image]",
        segments=[MessageSegment(type="image", data={"url": image_data})],
        reply_to=getattr(incoming, "msg_id", None) or None,
    )
