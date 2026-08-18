"""Telegram 适配器单元测试 (Fix-71 UTF-16 entity 切片)。"""

from __future__ import annotations

import pytest

from isac.channel.adapters.telegram.adapter import TelegramAdapter, _utf16_slice


def make_adapter() -> TelegramAdapter:
    return TelegramAdapter({"bot_token": "test"})


def tg_msg(text: str, entities: list[dict]) -> dict:
    return {
        "message_id": 1,
        "date": 1700000000,
        "chat": {"id": 100, "type": "private"},
        "from": {"id": 42, "username": "sender"},
        "text": text,
        "entities": entities,
    }


class TestUtf16Slice:
    def test_ascii_plain(self):
        assert _utf16_slice("hi @alice", 3, 6) == "@alice"

    def test_emoji_before_entity(self):
        # 🎉 占 2 个 UTF-16 unit / 1 个 code point; mention 的 offset 按 unit 计
        assert _utf16_slice("🎉 @alice hi", 3, 6) == "@alice"

    def test_smp_inside_prefix(self):
        # 实体前有两个 BMP 外字符 (4 unit) + 空格 (1 unit)
        assert _utf16_slice("🎉🚀 @bob", 5, 4) == "@bob"

    def test_out_of_range_returns_short_or_empty(self):
        assert _utf16_slice("abc", 10, 5) == ""
        assert _utf16_slice("abc", -1, 2) == ""
        assert _utf16_slice("abc", 0, 0) == ""


class TestMentionEntity:
    def test_mention_after_emoji_extracts_username(self):
        """Fix-71: emoji 在 mention 之前时按 code point 直切会错位
        (截出 'alice ' 而非 '@alice'), strip('@') 后 user_id 带空格。"""
        adapter = make_adapter()
        msg = adapter._to_isac_message(
            tg_msg("🎉 @alice hi", [{"type": "mention", "offset": 3, "length": 6}])
        )
        assert msg is not None
        at_segments = [s for s in msg.segments if s.type == "at"]
        assert len(at_segments) == 1
        assert at_segments[0].data["user_id"] == "alice"

    def test_plain_mention(self):
        adapter = make_adapter()
        msg = adapter._to_isac_message(
            tg_msg("@bob hello", [{"type": "mention", "offset": 0, "length": 4}])
        )
        assert msg is not None
        assert msg.segments[0].data["user_id"] == "bob"

    def test_malformed_entity_offset_does_not_crash(self):
        adapter = make_adapter()
        msg = adapter._to_isac_message(
            tg_msg("短文本", [{"type": "mention", "offset": 50, "length": 10}])
        )
        assert msg is not None
        at_segments = [s for s in msg.segments if s.type == "at"]
        assert len(at_segments) == 1
        assert at_segments[0].data["user_id"] == ""


# ── Fix-98: 超长回复分段发送 ─────────────────────────────


@pytest.mark.asyncio
async def test_send_chunks_overlong_reply(monkeypatch) -> None:
    """Fix-98: 超过 Telegram 4096 上限的回复必须分段发送 —— 此前整条提交 →
    平台 400 → send False → 用户完全收不到回复。"""
    from isac.channel.model import ISACMessage

    adapter = make_adapter()
    sent_texts: list[str] = []

    async def _fake_call_api(method, params):
        sent_texts.append(params.get("text", ""))
        return {"ok": True}

    monkeypatch.setattr(adapter, "_call_api", _fake_call_api)
    long_content = "x" * 9000  # > 4096*2
    msg = ISACMessage(
        msg_id="m1", platform="telegram", timestamp=0,
        user_id="u1", user_name="u1", group_id=None, content=long_content,
    )
    ok = await adapter.send(msg)
    assert ok is True
    assert len(sent_texts) == 3  # 4096 + 4096 + 808
    assert all(len(t) <= 4096 for t in sent_texts)
    assert "".join(sent_texts) == long_content


@pytest.mark.asyncio
async def test_send_short_reply_single_message(monkeypatch) -> None:
    """Fix-98 回归: 短回复不切分, 仍单条发送。"""
    from isac.channel.model import ISACMessage

    adapter = make_adapter()
    sent_texts: list[str] = []

    async def _fake_call_api(method, params):
        sent_texts.append(params.get("text", ""))
        return {"ok": True}

    monkeypatch.setattr(adapter, "_call_api", _fake_call_api)
    msg = ISACMessage(
        msg_id="m1", platform="telegram", timestamp=0,
        user_id="u1", user_name="u1", group_id=None, content="hello",
    )
    ok = await adapter.send(msg)
    assert ok is True
    assert sent_texts == ["hello"]
