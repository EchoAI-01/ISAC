"""J2 媒体制品 → Channel MessageSegment 解析器 (SPECIFICATION.md 2.4)。

生成结果 (ArtifactRef) 经本解析器转为各 Channel 适配器支持的 MessageSegment,
再由适配器走平台原生 API 发送; 不支持的平台返回 None (由调用方降级为文本占位)。

- OneBot (QQ): image/voice/video/file → CQSegment.image/record/video/file
- WebChat: 不支持媒体 segment, 返回 None (adapter 自己降级为文本占位)
- Telegram/Discord: 媒体发送留 J3, 当前返回 None
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.channel.model import MessageSegment

if TYPE_CHECKING:
    from isac.artifacts.models import ArtifactRef


# OneBot 平台 kind → MessageSegment.type 映射
# (注意: audio kind → voice type, 因为 OneBot 11 用 record/voice 表达音频段)
_ONEBOT_KIND_TO_TYPE: dict[str, str] = {
    "image": "image",
    "audio": "voice",
    "video": "video",
    "file": "file",
}

# 不支持媒体 segment 的平台 (返回 None, 由 adapter 自己降级)
_UNSUPPORTED_PLATFORMS: set[str] = {"webchat", "telegram", "discord"}

# Fix-63: OneBot 适配器的 platform_name 是 "qq" (onebot/adapter.py), 入站消息
# platform="qq"; 此前只匹配 "onebot" (仅配置节名) → QQ 富媒体出站永远命中
# 兜底 None 降级 (单测传字面量 "onebot" 掩盖了错位)。两者都接受。
_ONEBOT_PLATFORM_NAMES: frozenset[str] = frozenset({"onebot", "qq"})


class MediaResolver:
    """把 ArtifactRef 解析为 Channel 适配器支持的 MessageSegment。"""

    @staticmethod
    def resolve_for_channel(platform: str, artifact_ref: ArtifactRef | None) -> MessageSegment | None:
        """按平台能力把 ArtifactRef 转为 MessageSegment; 不支持返回 None。

        Args:
            platform: Channel 适配器名 ("onebot" / "webchat" / "telegram" / "discord" / ...)
            artifact_ref: 制品引用 (含 uri 指向本地文件路径)

        Returns:
            MessageSegment 或 None (调用方负责降级处理)
        """
        if artifact_ref is None:
            return None
        # 不支持的平台直接返回 None
        if platform in _UNSUPPORTED_PLATFORMS:
            return None
        # OneBot 平台: 按 kind 映射到 segment type, url 指向 ref.uri
        if platform in _ONEBOT_PLATFORM_NAMES:
            seg_type = _ONEBOT_KIND_TO_TYPE.get(artifact_ref.kind)
            if seg_type is None:
                return None
            return MessageSegment(
                type=seg_type,
                data={"url": artifact_ref.uri, "artifact_id": artifact_ref.artifact_id},
            )
        # 其他未明确支持的平台: 返回 None
        return None
