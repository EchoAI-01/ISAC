"""J2 媒体制品 → Channel MessageSegment 解析器 (SPECIFICATION.md 2.4)。

生成结果 (ArtifactRef) 经本解析器转为各 Channel 适配器支持的 MessageSegment,
再由适配器走平台原生 API 发送; 不支持的平台返回 None (由调用方降级为文本占位)。

- OneBot (QQ): image/voice/video/file → CQSegment.image/record/video/file
- 飞书 (feishu): 富媒体二波 (2026-10-11) —— image 制品 → image segment (适配器
  读本地文件上传 im/v1/images 得 image_key 后发送); 其余 kind 暂不支持。
- Discord: 富媒体二波 (2026-10-11) —— image/video/audio/file 全 kind → 对应
  segment (适配器 multipart 附件发送)。
- WebChat/Telegram: 不支持媒体 segment, 返回 None (adapter 自己降级为文本占位)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from isac.channel.model import MessageSegment
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.artifacts.models import ArtifactRef

logger = get_logger(__name__)


# OneBot 平台 kind → MessageSegment.type 映射
# (注意: audio kind → voice type, 因为 OneBot 11 用 record/voice 表达音频段)
_ONEBOT_KIND_TO_TYPE: dict[str, str] = {
    "image": "image",
    "audio": "voice",
    "video": "video",
    "file": "file",
}

# Discord kind → segment type (直接同名; 音频 Discord 用 audio)
_DISCORD_KIND_TO_TYPE: dict[str, str] = {
    "image": "image",
    "audio": "audio",
    "video": "video",
    "file": "file",
}

# 不支持媒体 segment 的平台 (返回 None, 由 adapter 自己降级)
_UNSUPPORTED_PLATFORMS: set[str] = {"webchat", "telegram"}

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
        # 飞书: 富媒体二波 —— image 制品 (适配器上传后以 msg_type=image 发送)。
        if platform == "feishu" and artifact_ref.kind == "image":
            return MessageSegment(
                type="image",
                data={
                    "media_uri": artifact_ref.uri,
                    "artifact_id": artifact_ref.artifact_id,
                    # R2: 制品文件名是 sha256.bin (无扩展名), MIME 必须随 ref 透传,
                    # 否则适配器只能 image/png 兜底猜测。
                    "mime_type": artifact_ref.mime_type,
                },
            )
        # Discord: 富媒体二波 —— 全 kind multipart 附件。
        if platform == "discord":
            seg_type = _DISCORD_KIND_TO_TYPE.get(artifact_ref.kind)
            if seg_type is None:
                return None
            return MessageSegment(
                type=seg_type,
                data={
                    "media_uri": artifact_ref.uri,
                    "artifact_id": artifact_ref.artifact_id,
                    "mime_type": artifact_ref.mime_type,
                },
            )
        # 其他未明确支持的平台: 返回 None
        return None


# ── R2 (2026-10-13 review 修复): 出站媒体本地路径防线 ──────────────
# 富媒体二波给出站新增了"读本地文件 → 经平台 API 上传"的面 (飞书 im/v1/images
# multipart / Discord files[N]), 此前两处适配器各自判断"是否本地路径"且判断全错:
# - 飞书 startswith(("data/uploads", "/")) 把**所有绝对路径**放行 (/etc/passwd
#   也符合), 相对制品目录 data/artifacts 反而被拒 (generate_image 制品永远发不出);
# - Discord 对任意非 http 路径直接 read_bytes, 无任何限制。
# segment 的 media_uri/url 是 LLM 工具参数/兼容层插件可构造的内容, 该面等效
# "任意本地文件读取外传"。统一防线: 只允许 ArtifactStore 两个根目录
# (data/artifacts 出站生成 / data/uploads 入站落盘, 与 wiring.py DATA_DIR 同源),
# 拒 .. 穿越 / symlink 逃逸 / 白名单外绝对路径 / 超大文件 —— 口径对齐
# utils/media.py MediaNormalizer (入站侧白名单) 但独立实现: 出站制品文件名是
# sha256.bin (无扩展名可推 MIME), MediaNormalizer 的 MIME 推断不适用。
_OUTBOUND_MEDIA_ROOTS: tuple[str, ...] = ("data/artifacts", "data/uploads")
# 与 MediaNormalizer image 上限对齐 (25MB); 飞书 im/v1/images 上限 10MB、Discord
# 普通附件 10MB —— 平台侧更紧的限制由其 API 报错降级兜底, 宿主侧先挡明显滥用。
OUTBOUND_MEDIA_MAX_BYTES = 25 * 1024 * 1024


def validate_outbound_media_path(
    raw: str, *, max_bytes: int = OUTBOUND_MEDIA_MAX_BYTES
) -> Path | None:
    """校验出站媒体 segment 的本地文件路径; 非法/越界/超限返回 None (调用方降级)。

    返回 resolved 绝对路径 (symlink 已展开)。http(s) URL 返回 None —— 平台回传
    URL 无本地字节, 不属本防线, 由调用方跳过或降级占位 (维持既有语义)。
    """
    if not raw or raw.startswith(("http://", "https://", "data:")):
        return None
    p = Path(raw)
    if ".." in p.parts:
        logger.warning("出站媒体路径含 .. 穿越, 拒绝", path=raw[:120])
        return None
    resolved = p if p.is_absolute() else (Path.cwd() / p)
    try:
        resolved = resolved.resolve(strict=False)
        roots = [(Path.cwd() / r).resolve(strict=False) for r in _OUTBOUND_MEDIA_ROOTS]
    except OSError:
        return None
    if not any(resolved == r or r in resolved.parents for r in roots):
        logger.warning("出站媒体路径不在制品根目录内, 拒绝", path=raw[:120])
        return None
    try:
        if not resolved.is_file():
            return None
        if resolved.stat().st_size > max_bytes:
            logger.warning(
                "出站媒体文件超上限, 拒绝", path=raw[:120], size=resolved.stat().st_size, max=max_bytes
            )
            return None
    except OSError:
        return None
    return resolved
