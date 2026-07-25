"""J2 阶段 7: MediaResolver 单元测试。

覆盖:
- OneBot 平台: image/audio/video/file ArtifactRef → 对应 MessageSegment
  (image/voice/video/file 类型, data.url 指向 ref.uri)
- WebChat 平台: 任何 ArtifactRef 返回 None (WebChat 自己降级为文本占位)
- Telegram/Discord 平台: 任何 ArtifactRef 返回 None (TODO J3)
- 未知平台: 返回 None
- kind 不在 image|audio|video|file 范围: 返回 None
"""

from __future__ import annotations

import pytest

from isac.artifacts.models import ArtifactRef
from isac.channel.media_resolver import MediaResolver


def _ref(kind: str, *, mime_type: str = "", artifact_id: str = "abc123def456") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        kind=kind,
        mime_type=mime_type or f"application/{kind}",
        uri=f"/data/artifacts/{kind}/{artifact_id}.bin",
        size_bytes=100,
    )


def test_resolve_image_for_onebot() -> None:
    ref = _ref("image", mime_type="image/png")
    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "image"
    assert seg.data.get("url") == ref.uri


def test_resolve_audio_for_onebot() -> None:
    ref = _ref("audio", mime_type="audio/mpeg")
    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "voice"  # OneBot 用 record/voice 表达音频
    assert seg.data.get("url") == ref.uri


def test_resolve_video_for_onebot() -> None:
    ref = _ref("video", mime_type="video/mp4")
    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "video"
    assert seg.data.get("url") == ref.uri


def test_resolve_file_for_onebot() -> None:
    ref = _ref("file", mime_type="application/octet-stream")
    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "file"
    assert seg.data.get("url") == ref.uri


def test_resolve_for_webchat_returns_none() -> None:
    # WebChat 不支持媒体 segment, 由 adapter 自己降级为文本占位
    ref = _ref("image")
    assert MediaResolver.resolve_for_channel("webchat", ref) is None


def test_resolve_for_telegram_returns_none() -> None:
    # Telegram 媒体 segment 留 J3
    ref = _ref("image")
    assert MediaResolver.resolve_for_channel("telegram", ref) is None


def test_resolve_for_discord_returns_none() -> None:
    ref = _ref("audio")
    assert MediaResolver.resolve_for_channel("discord", ref) is None


def test_resolve_unknown_platform_returns_none() -> None:
    ref = _ref("image")
    assert MediaResolver.resolve_for_channel("unknown_platform", ref) is None


def test_resolve_unknown_kind_returns_none() -> None:
    # kind 不在 image|audio|video|file 范围 → None
    ref = _ref("embedding")  # 不合法的 kind
    assert MediaResolver.resolve_for_channel("onebot", ref) is None


def test_resolve_for_none_returns_none() -> None:
    # ref 为 None 时返回 None (调用方可能传 None)
    assert MediaResolver.resolve_for_channel("onebot", None) is None  # type: ignore[arg-type]


# ── WebChatAdapter.send 把非 text segment 降级为占位文本 ──────────


@pytest.mark.asyncio
async def test_webchat_send_degrades_image_segment_to_placeholder() -> None:
    """WebChat 不支持富媒体 segment, send 把 image seg 降级为 [image: <id[:8]>] 文本。"""
    from isac.channel.adapters.webchat.adapter import WebChatAdapter
    from isac.channel.model import ISACMessage, MessageSegment

    adapter = WebChatAdapter({})
    msg = ISACMessage(
        msg_id="", platform="webchat", timestamp=0,
        user_id="u1", user_name="",
        content="已生成图片", session_id="s1",
        segments=[MessageSegment(type="image", data={"artifact_id": "abc123def456"})],
    )
    await adapter.send(msg)
    replies = await adapter.poll_replies("s1")
    assert len(replies) == 1
    # content 应追加占位: "已生成图片 [image: abc123de]" (artifact_id 前 8 字符)
    assert "已生成图片" in replies[0]["content"]
    assert "[image: abc123de]" in replies[0]["content"]


@pytest.mark.asyncio
async def test_webchat_send_text_only_no_placeholder() -> None:
    """无 segment 时 content 不追加任何占位。"""
    from isac.channel.adapters.webchat.adapter import WebChatAdapter
    from isac.channel.model import ISACMessage

    adapter = WebChatAdapter({})
    msg = ISACMessage(
        msg_id="", platform="webchat", timestamp=0,
        user_id="u1", user_name="",
        content="纯文本回复", session_id="s1",
    )
    await adapter.send(msg)
    replies = await adapter.poll_replies("s1")
    assert replies[0]["content"] == "纯文本回复"


@pytest.mark.asyncio
async def test_webchat_send_multiple_segments_all_placeholders() -> None:
    """多个非 text segment 都追加占位 (image + audio)。"""
    from isac.channel.adapters.webchat.adapter import WebChatAdapter
    from isac.channel.model import ISACMessage, MessageSegment

    adapter = WebChatAdapter({})
    msg = ISACMessage(
        msg_id="", platform="webchat", timestamp=0,
        user_id="u1", user_name="",
        content="成果", session_id="s1",
        segments=[
            MessageSegment(type="image", data={"artifact_id": "img1234567"}),
            MessageSegment(type="voice", data={"artifact_id": "aud7654321"}),
        ],
    )
    await adapter.send(msg)
    replies = await adapter.poll_replies("s1")
    content = replies[0]["content"]
    assert "[image: img12345]" in content
    assert "[voice: aud76543]" in content
