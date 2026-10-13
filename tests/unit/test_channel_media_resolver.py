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

from pathlib import Path

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


def test_resolve_for_discord_full_kinds() -> None:
    """富媒体二波: Discord 全 kind → 对应 segment (multipart 附件发送)。"""
    assert MediaResolver.resolve_for_channel("discord", _ref("audio")) is not None
    assert MediaResolver.resolve_for_channel("discord", _ref("image")).type == "image"  # type: ignore[union-attr]
    # 未知 kind 仍 None
    assert MediaResolver.resolve_for_channel("discord", _ref("sticker")) is None


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


# ── R2 (2026-10-13 review 修复): 出站媒体本地路径防线 ──────────


class TestValidateOutboundMediaPath:
    """出站本地路径防线: 只放行 ArtifactStore 根内文件, 拒穿越/越界/超限。

    修复前的两处反面教材: 飞书 startswith(("data/uploads", "/")) 放行所有
    绝对路径 (/etc/passwd 也符合) 且拒 data/artifacts 制品; Discord 对任意
    非 http 本地路径直接 read_bytes。
    """

    def test_http_and_data_uri_rejected(self) -> None:
        from isac.channel.media_resolver import validate_outbound_media_path

        assert validate_outbound_media_path("https://cdn.example.com/x.png") is None
        assert validate_outbound_media_path("data:image/png;base64,xxx") is None
        assert validate_outbound_media_path("") is None

    def test_traversal_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from isac.channel.media_resolver import validate_outbound_media_path

        monkeypatch.chdir(tmp_path)
        assert validate_outbound_media_path("data/uploads/../../etc/passwd") is None

    def test_outside_whitelist_absolute_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """绝对路径一律不放行 (修复前 /etc/passwd 通过飞书检查)。"""
        from isac.channel.media_resolver import validate_outbound_media_path

        monkeypatch.chdir(tmp_path)
        assert validate_outbound_media_path("/etc/passwd") is None
        # 制品根之外的绝对路径同样拒绝 (即使存在且在根下层级相似)。
        outside = tmp_path / "elsewhere" / "x.bin"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"x")
        assert validate_outbound_media_path(str(outside)) is None

    def test_artifact_roots_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from isac.channel.media_resolver import validate_outbound_media_path

        monkeypatch.chdir(tmp_path)
        for root in ("data/artifacts", "data/uploads"):
            f = tmp_path / root / "ab" / "sha256.bin"
            f.parent.mkdir(parents=True)
            f.write_bytes(b"payload")
            resolved = validate_outbound_media_path(f"{root}/ab/sha256.bin")
            assert resolved is not None and resolved.name == "sha256.bin"

    def test_size_cap_enforced(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from isac.channel.media_resolver import validate_outbound_media_path

        monkeypatch.chdir(tmp_path)
        f = tmp_path / "data" / "uploads" / "big.bin"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"x" * 32)
        assert validate_outbound_media_path("data/uploads/big.bin", max_bytes=16) is None
        assert validate_outbound_media_path("data/uploads/big.bin", max_bytes=64) is not None

    def test_missing_file_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from isac.channel.media_resolver import validate_outbound_media_path

        monkeypatch.chdir(tmp_path)
        assert validate_outbound_media_path("data/uploads/nope.bin") is None


class TestAdapterOutboundMediaDefense:
    """适配器级: 越界 segment 不得触发任何本地读盘/上传。"""

    @pytest.mark.asyncio
    async def test_feishu_outbound_image_outside_roots_degrades(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """飞书: 绝对路径 segment (修复前被 startswith("/") 放行) → 降级占位,
        且绝不发生本地文件读取 (read_bytes 未被调用)。"""
        from isac.channel.adapters.feishu.adapter import FeishuAdapter
        from isac.channel.model import ISACMessage, MessageSegment

        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRET")
        adapter = FeishuAdapter({"app_id": "a", "app_secret": "s"})
        msg = ISACMessage(
            msg_id="", platform="feishu", timestamp=0, user_id="ou_1", user_name="",
            group_id=None, session_id="s1", content="",
            segments=[MessageSegment(type="image", data={"media_uri": str(secret)})],
        )
        calls: list[str] = []

        async def _no_read(*_a: object, **_k: object) -> bytes:  # pragma: no cover
            calls.append("read")
            raise AssertionError("越界路径不得读盘")

        import pathlib

        monkeypatch.setattr(pathlib.Path, "read_bytes", _no_read)
        # token 换取直接给桩, 隔离网络。
        async def _token() -> str:
            return "t"

        monkeypatch.setattr(adapter, "_get_tenant_access_token", _token)
        sent_placeholders: list[str] = []

        async def _placeholder(token: str, rid: str, ridt: str, text: str) -> bool:
            sent_placeholders.append(text)
            return True

        monkeypatch.setattr(adapter, "_send_text_placeholder", _placeholder)

        async def _http_post(url: str, **_k: object) -> dict:
            return {"code": 0}

        monkeypatch.setattr(adapter, "_http_post", _http_post)
        ok = await adapter.send(msg)
        assert ok is True
        assert sent_placeholders == ["[图片]"]
        assert not calls

    @pytest.mark.asyncio
    async def test_discord_outbound_attachment_outside_roots_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Discord: 任意非 http 本地路径 (修复前直接 read_bytes) → 全部跳过,
        仅发文本段 (不触发 multipart)。"""
        from isac.channel.adapters.discord.adapter import DiscordAdapter
        from isac.channel.model import ISACMessage, MessageSegment

        adapter = DiscordAdapter({"bot_token": "x"})
        secret = tmp_path / "secret.txt"
        secret.write_text("TOPSECRET")
        msg = ISACMessage(
            msg_id="", platform="discord", timestamp=0, user_id="u", user_name="",
            group_id="chan1", session_id="s1", content="hello",
            segments=[
                MessageSegment(type="image", data={"url": str(secret)}),
                MessageSegment(type="file", data={"url": "data/uploads/../../etc/passwd"}),
            ],
        )

        async def _no_multipart(*_a: object, **_k: object) -> object:
            raise AssertionError("无合法附件时不得走 multipart")

        monkeypatch.setattr(adapter, "_send_multipart", _no_multipart)
        api_calls: list[tuple[str, str]] = []

        async def _call_api(method: str, path: str, **_k: object) -> dict:
            api_calls.append((method, path))
            return {"id": "1"}

        monkeypatch.setattr(adapter, "_call_api", _call_api)
        ok = await adapter.send(msg)
        assert ok is True
        # 只有纯文本 POST, 无 multipart 调用 (异常即测试失败)。
        assert api_calls == [("POST", "/channels/chan1/messages")]
