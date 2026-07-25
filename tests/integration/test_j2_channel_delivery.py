"""J2 阶段 9: 媒体制品经 Channel 适配器发送的集成测试。

覆盖:
- ArtifactRef → MediaResolver → WebChat 文本占位降级 (WebChat 不支持富媒体)
- ArtifactRef → MediaResolver → OneBot MessageSegment (image/voice/video/file)
- OneBotAdapter._to_cq_segment 把 image MessageSegment 转为 CQSegment.image
- WebChatAdapter.send 把 image segment 降级为 [image: <id[:8]>] 占位追加到 content
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.artifacts.store import ArtifactStore
from isac.channel.adapters.webchat.adapter import WebChatAdapter
from isac.channel.media_resolver import MediaResolver
from isac.channel.model import ISACMessage, MessageSegment


@pytest.mark.asyncio
async def test_artifact_ref_to_webchat_text_placeholder(tmp_path: Path) -> None:
    """ArtifactRef → MediaResolver (webchat) 返回 None → 调用方降级为占位文本
    → WebChatAdapter.send 把 segment 转为 [image: <id[:8]>] 追加到 content。"""
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    ref = await artifact_store.put(
        b"\x89PNG fake image bytes", kind="image", mime_type="image/png"
    )

    # MediaResolver 对 webchat 返回 None (调用方需降级处理)
    seg = MediaResolver.resolve_for_channel("webchat", ref)
    assert seg is None

    # 模拟调用方降级: 构造一条带 image segment 的 ISACMessage
    # (实际生产代码会由 main._send_reply 在 reply 含 ArtifactRef 时填充,
    #  J2 范围内 _send_reply 未改造, 留 J3; 这里手动构造测试 adapter 行为)
    msg = ISACMessage(
        msg_id="", platform="webchat", timestamp=0,
        user_id="u1", user_name="",
        content="已生成图片", session_id="s1",
        segments=[
            MessageSegment(
                type="image",
                data={"url": ref.uri, "artifact_id": ref.artifact_id},
            )
        ],
    )
    adapter = WebChatAdapter({})
    await adapter.send(msg)
    replies = await adapter.poll_replies("s1")
    assert len(replies) == 1
    content = replies[0]["content"]
    assert "已生成图片" in content
    assert "[image: " in content
    # artifact_id 前 8 字符应在占位里
    assert ref.artifact_id[:8] in content
    # frame 仍标记为 message (非 progress)
    assert replies[0]["kind"] == "message"


@pytest.mark.asyncio
async def test_artifact_ref_to_onebot_image_segment(tmp_path: Path) -> None:
    """ArtifactRef (kind=image) → MediaResolver (onebot) → MessageSegment(type=image) →
    OneBotAdapter._to_cq_segment → CQSegment.image(url)。"""
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    ref = await artifact_store.put(
        b"\x89PNG fake image bytes", kind="image", mime_type="image/png"
    )

    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "image"
    assert seg.data["url"] == ref.uri
    assert seg.data["artifact_id"] == ref.artifact_id

    # OneBotAdapter._to_cq_segment 转 CQSegment (需要 aiocqhttp)
    try:
        from aiocqhttp import MessageSegment as CQSegment
    except ImportError:
        pytest.skip("aiocqhttp 未安装 (onebot extra)")

    from isac.channel.adapters.onebot.adapter import OneBotAdapter
    adapter = OneBotAdapter({})
    cq_seg = adapter._to_cq_segment(seg, CQSegment)
    assert cq_seg is not None
    # aiocqhttp MessageSegment 是 dict 子类, 含 type + data
    assert cq_seg["type"] == "image"
    assert cq_seg["data"]["file"] == ref.uri or cq_seg["data"].get("url") == ref.uri


@pytest.mark.asyncio
async def test_artifact_ref_to_onebot_audio_segment(tmp_path: Path) -> None:
    """ArtifactRef (kind=audio) → MediaResolver → MessageSegment(type=voice) →
    OneBotAdapter._to_cq_segment → CQSegment.record (OneBot 11 用 record 表达音频)。"""
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    ref = await artifact_store.put(
        b"ID3fake mp3 audio bytes", kind="audio", mime_type="audio/mpeg"
    )

    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "voice"

    try:
        from aiocqhttp import MessageSegment as CQSegment
    except ImportError:
        pytest.skip("aiocqhttp 未安装 (onebot extra)")

    from isac.channel.adapters.onebot.adapter import OneBotAdapter
    adapter = OneBotAdapter({})
    cq_seg = adapter._to_cq_segment(seg, CQSegment)
    assert cq_seg is not None
    assert cq_seg["type"] == "record"


@pytest.mark.asyncio
async def test_artifact_ref_to_onebot_video_segment(tmp_path: Path) -> None:
    """ArtifactRef (kind=video) → MessageSegment(type=video) → CQSegment.video。"""
    artifact_store = ArtifactStore(str(tmp_path / "artifacts"))
    ref = await artifact_store.put(
        b"\x00\x00\x00 ftypisomfake video", kind="video", mime_type="video/mp4"
    )

    seg = MediaResolver.resolve_for_channel("onebot", ref)
    assert seg is not None
    assert seg.type == "video"

    try:
        from aiocqhttp import MessageSegment as CQSegment
    except ImportError:
        pytest.skip("aiocqhttp 未安装 (onebot extra)")

    from isac.channel.adapters.onebot.adapter import OneBotAdapter
    adapter = OneBotAdapter({})
    cq_seg = adapter._to_cq_segment(seg, CQSegment)
    assert cq_seg is not None
    assert cq_seg["type"] == "video"
