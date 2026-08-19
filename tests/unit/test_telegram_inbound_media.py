"""阶段3-1 第一波: Telegram 入站富媒体解析 + 入站下载 URL 日志脱敏。

验收:
- Telegram photo/voice/video/animation/audio/document 的 file_id 被解析成 media segment;
- photo 取分辨率最高的 (最后一个); animation 归 image;
- getFile 解析失败/空 → 跳过该媒体, 不阻塞消息;
- 入站下载日志对 ``/bot<token>/`` 与 token 查询参数脱敏 (不泄露凭据)。
"""

from __future__ import annotations

import pytest

from isac.channel.adapters.telegram.adapter import TelegramAdapter
from isac.gateway.incoming_media import _mask_url_for_log


def make_adapter() -> TelegramAdapter:
    return TelegramAdapter({"bot_token": "123456:SECRET", "api_base": "https://api.telegram.org"})


def tg_media_msg(**media_fields) -> dict:
    base = {
        "message_id": 1,
        "date": 1700000000,
        "chat": {"id": 100, "type": "private"},
        "from": {"id": 42, "username": "sender"},
    }
    base.update(media_fields)
    return base


# ── _extract_media: 纯解析 ─────────────────────────────────────


def test_extract_photo_takes_largest() -> None:
    msg = tg_media_msg(photo=[
        {"file_id": "small", "width": 90},
        {"file_id": "mid", "width": 320},
        {"file_id": "largest", "width": 1280},
    ])
    media = TelegramAdapter._extract_media(msg)  # noqa: SLF001
    assert media == [{"kind": "image", "file_id": "largest", "file_name": ""}]


def test_extract_voice_video_document_audio() -> None:
    msg = tg_media_msg(voice={"file_id": "v1"})
    assert TelegramAdapter._extract_media(msg) == [  # noqa: SLF001
        {"kind": "voice", "file_id": "v1", "file_name": ""}
    ]
    msg = tg_media_msg(document={"file_id": "d1", "file_name": "report.pdf"})
    assert TelegramAdapter._extract_media(msg) == [  # noqa: SLF001
        {"kind": "file", "file_id": "d1", "file_name": "report.pdf"}
    ]
    msg = tg_media_msg(video={"file_id": "vid1"})
    assert TelegramAdapter._extract_media(msg)[0]["kind"] == "video"  # noqa: SLF001
    msg = tg_media_msg(audio={"file_id": "a1"})
    assert TelegramAdapter._extract_media(msg)[0]["kind"] == "audio"  # noqa: SLF001


def test_extract_animation_maps_to_image() -> None:
    msg = tg_media_msg(animation={"file_id": "gif1"})
    assert TelegramAdapter._extract_media(msg)[0]["kind"] == "image"  # noqa: SLF001


def test_extract_no_media_returns_empty() -> None:
    assert TelegramAdapter._extract_media(tg_media_msg(text="hello")) == []  # noqa: SLF001


def test_extract_ignores_malformed() -> None:
    # photo 空列表 / file_id 缺失 / 非 dict 都不产出。
    assert TelegramAdapter._extract_media(tg_media_msg(photo=[])) == []  # noqa: SLF001
    assert TelegramAdapter._extract_media(tg_media_msg(document={"no_id": 1})) == []  # noqa: SLF001
    assert TelegramAdapter._extract_media(tg_media_msg(voice="not-a-dict")) == []  # noqa: SLF001


# ── _resolve_file_url: getFile → 下载 URL ──────────────────────


@pytest.mark.asyncio
async def test_resolve_file_url_builds_file_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = make_adapter()

    async def _fake_call_api(method: str, params: dict | None = None):
        assert method == "getFile"
        assert params == {"file_id": "abc"}
        return {"file_id": "abc", "file_path": "photos/file_0.jpg"}

    monkeypatch.setattr(adapter, "_call_api", _fake_call_api)
    url = await adapter._resolve_file_url("abc")  # noqa: SLF001
    assert url == "https://api.telegram.org/file/bot123456:SECRET/photos/file_0.jpg"


@pytest.mark.asyncio
async def test_resolve_file_url_none_when_no_path(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = make_adapter()

    async def _fake_call_api(method: str, params: dict | None = None):
        return {"file_id": "abc"}  # 无 file_path

    monkeypatch.setattr(adapter, "_call_api", _fake_call_api)
    assert await adapter._resolve_file_url("abc") is None  # noqa: SLF001

    async def _fake_none(method: str, params: dict | None = None):
        return None

    monkeypatch.setattr(adapter, "_call_api", _fake_none)
    assert await adapter._resolve_file_url("abc") is None  # noqa: SLF001


# ── _attach_media_segments: 追加 segment ───────────────────────


@pytest.mark.asyncio
async def test_attach_media_segments_appends_url_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = make_adapter()

    async def _fake_resolve(file_id: str):
        return f"https://api.telegram.org/file/bot123456:SECRET/{file_id}.jpg"

    monkeypatch.setattr(adapter, "_resolve_file_url", _fake_resolve)
    isac_msg = adapter._to_isac_message(tg_media_msg(text=""))  # noqa: SLF001
    assert isac_msg is not None
    await adapter._attach_media_segments(  # noqa: SLF001
        tg_media_msg(photo=[{"file_id": "ph1"}]), isac_msg
    )
    image_segs = [s for s in isac_msg.segments if s.type == "image"]
    assert len(image_segs) == 1
    assert image_segs[0].data["file_id"] == "ph1"
    assert image_segs[0].data["url"].endswith("ph1.jpg")


@pytest.mark.asyncio
async def test_attach_media_segments_skips_unresolved(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = make_adapter()

    async def _fake_resolve(file_id: str):
        return None  # getFile 失败

    monkeypatch.setattr(adapter, "_resolve_file_url", _fake_resolve)
    isac_msg = adapter._to_isac_message(tg_media_msg(text="hi"))  # noqa: SLF001
    assert isac_msg is not None
    before = len(isac_msg.segments)
    await adapter._attach_media_segments(tg_media_msg(photo=[{"file_id": "x"}]), isac_msg)  # noqa: SLF001
    assert len(isac_msg.segments) == before  # 解析失败 → 不追加, 不崩溃


# ── _mask_url_for_log: 凭据脱敏 ────────────────────────────────


def test_mask_url_hides_bot_token_path() -> None:
    url = "https://api.telegram.org/file/bot123456:SECRET/photos/a.jpg"
    masked = _mask_url_for_log(url)
    assert "123456:SECRET" not in masked
    assert "/bot***masked***/" in masked
    assert masked.endswith("photos/a.jpg")


def test_mask_url_hides_token_query_param() -> None:
    url = "https://example.com/media?access_token=abc123&id=7"
    masked = _mask_url_for_log(url)
    assert "abc123" not in masked
    assert "access_token=***" in masked
    assert "id=7" in masked  # 非敏感参数保留


def test_mask_url_plain_url_unchanged() -> None:
    url = "https://example.com/img/pic.png"
    assert _mask_url_for_log(url) == url
