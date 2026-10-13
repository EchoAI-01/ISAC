"""send_image 工具: 生成图片并经原 Channel 直接发送 (L1, 2026-10-13 review 重写)。

修复前 (08-21 盘点遗留①): 依赖的 channel_send 服务键全仓零注入 → 工具 LLM 可见
但调用恒失败; 且实现按旧 ImageGenProvider 契约 (generate 返回 bytes) 把返回值
直接塞进 segment data.url —— 两头都是死路。重写为 J2 管线: model_router 选路 →
ImageGenerationProvider.generate → ArtifactRef → MediaResolver 按当前平台转
segment → channel_send 经原适配器发送; 平台不支持媒体段 / channel_send 未注入时
不硬发, 把 artifact 引用交还 LLM (回复文本引用同一制品, dispatch 出站会转 segment)。
"""

from __future__ import annotations

from typing import Any

from isac.agent.tools.base import ToolResult
from isac.agent.tools.media import _MediaToolBase


class SendImageTool(_MediaToolBase):
    """生成一张图片并直接发送到当前会话 (不经回复文本)。"""

    _operation = "image_gen"
    _modalities_in = {"text"}
    _modalities_out = {"image"}

    @property
    def name(self) -> str:
        return "send_image"

    @property
    def description(self) -> str:
        return "生成一张图片并直接发送到当前会话"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "图片内容描述"}},
            "required": ["prompt"],
        }

    async def _call_provider(
        self, provider: Any, context: Any, artifact_store: Any
    ) -> ToolResult:
        prompt = str(context.args.get("prompt", "") or "").strip()
        if not prompt:
            return ToolResult(content="send_image 缺少 prompt。", is_error=True)
        refs = await provider.generate(prompt, n=1)
        if not refs:
            return ToolResult(content="图片生成返回空结果。", is_error=True)
        return await self._deliver(refs[0], context, prompt)

    async def _deliver(self, ref: Any, context: Any, prompt: str) -> ToolResult:
        """制品 → 平台 segment → channel_send; 不可直发时把 artifact 引用交还 LLM。"""
        from isac.channel.media_resolver import MediaResolver
        from isac.channel.model import ISACMessage

        incoming = context.agent_context.current_message
        platform = str(getattr(incoming, "platform", "") or "")
        seg = MediaResolver.resolve_for_channel(platform, ref)
        sender = context.services.channel_send
        # 降级链: 平台不支持媒体段 (webchat/telegram 等) 或发送服务未注入 → 不硬发,
        # 返回 artifact 引用让 LLM 走"回复文本引用 + dispatch 出站转段"的标准路径。
        if sender is None or seg is None:
            return ToolResult(
                content=(
                    f"图片已生成 (artifact:{ref.artifact_id}), 但当前会话不支持直接发送; "
                    "可在回复文本中引用该 artifact, 出站时会转为媒体段。"
                )
            )
        # WebChat 等按平台会话键路由的平台须用 platform_session_id (出站路由口径
        # 同 outbound._send_reply: 平台键优先, 回退内部 session_id)。
        session = getattr(context.agent_context, "session", None)
        platform_session_id = str(getattr(session, "platform_session_id", "") or "")
        reply = ISACMessage(
            msg_id="",
            platform=platform,
            timestamp=0,
            user_id=getattr(incoming, "user_id", ""),
            user_name="",
            group_id=getattr(incoming, "group_id", None),
            session_id=platform_session_id or str(getattr(incoming, "session_id", "") or ""),
            content="",
            segments=[seg],
            reply_to=getattr(incoming, "msg_id", None) or None,
        )
        try:
            ok = await sender(reply)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                content=f"图片发送失败: {exc}; 制品 artifact:{ref.artifact_id} 可在回复文本中引用。",
                is_error=True,
            )
        if not ok:
            return ToolResult(
                content=(
                    f"图片发送未成功 (平台返回失败); 制品 artifact:{ref.artifact_id} "
                    "可在回复文本中引用。"
                ),
                is_error=True,
            )
        return ToolResult(content=f"已发送图片 (prompt={prompt[:40]})")
