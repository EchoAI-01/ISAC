"""第三轮审查批 2 dispatch 级回归测试 (Fix-95 metadata 透传 / Fix-99 loopback 配置)。"""

from __future__ import annotations

import pytest

from isac.channel.model import ISACMessage

# ── Fix-95: _send_reply 透传 incoming.metadata ─────────────────


@pytest.mark.asyncio
async def test_send_reply_propagates_incoming_metadata() -> None:
    """Fix-95: 出站回复必须带上 incoming.metadata —— qq_official send() 依赖
    metadata['qq_official_source'] 选频道端点; 此前出站不带 metadata → 频道回复
    100% 走错端点发送失败。"""
    from isac.dispatch import _send_reply

    captured: list[ISACMessage] = []

    class _FakeAdapter:
        async def send(self, message: ISACMessage) -> bool:
            captured.append(message)
            return True

    class _FakeRegistry:
        def get(self, platform: str):
            return _FakeAdapter()

    incoming = ISACMessage(
        msg_id="m-in", platform="qq_official", timestamp=0,
        user_id="u1", user_name="u1", group_id="chan-1",
        content="hi", metadata={"qq_official_source": "AT_MESSAGE_CREATE"},
    )
    await _send_reply(_FakeRegistry(), incoming, "回复内容", "agent_a")
    assert len(captured) == 1
    assert captured[0].metadata.get("qq_official_source") == "AT_MESSAGE_CREATE"


@pytest.mark.asyncio
async def test_progress_sender_merges_incoming_metadata() -> None:
    """Fix-95: 进度帧同样合并 incoming.metadata (进度专属键覆盖在后)。"""
    from isac.dispatch import _make_progress_sender

    captured: list[ISACMessage] = []

    class _FakeAdapter:
        async def send(self, message: ISACMessage) -> bool:
            captured.append(message)
            return True

    class _FakeRegistry:
        def get(self, platform: str):
            return _FakeAdapter()

    incoming = ISACMessage(
        msg_id="m-in", platform="qq_official", timestamp=0,
        user_id="u1", user_name="u1", group_id="chan-1",
        content="hi", metadata={"qq_official_source": "AT_MESSAGE_CREATE"},
    )
    sender = _make_progress_sender(_FakeRegistry(), incoming, "agent_a")

    class _Event:
        task_id = "t1"
        stage = "running"

    await sender("处理中…", _Event())
    assert len(captured) == 1
    assert captured[0].metadata.get("qq_official_source") == "AT_MESSAGE_CREATE"
    assert captured[0].metadata.get("message_kind") == "progress"


# ── Fix-99: 入站媒体 allow_loopback 配置透传 ───────────────────


@pytest.mark.asyncio
async def test_inbound_media_allow_loopback_from_global_config(monkeypatch) -> None:
    """Fix-99: global_config inbound_media.allow_loopback=True 时透传到
    download_inbound_media (OneBot/NapCat 同机媒体白名单)。"""
    import isac.dispatch as dispatch_mod

    seen: dict = {}

    async def _fake_download(message, store, *, http_client=None, allow_loopback=False):
        seen["allow_loopback"] = allow_loopback
        return 0

    monkeypatch.setattr(dispatch_mod, "download_inbound_media", _fake_download)

    class _FakeAgentManager:
        _services = {
            "uploads_store": object(),
            "global_config": {"inbound_media": {"allow_loopback": True}},
        }

    msg = ISACMessage(msg_id="m", platform="onebot", timestamp=0, user_id="u", user_name="u")
    await dispatch_mod._download_inbound_media_safe(msg, _FakeAgentManager())
    assert seen["allow_loopback"] is True


@pytest.mark.asyncio
async def test_inbound_media_loopback_default_off(monkeypatch) -> None:
    """Fix-99 回归: 未配置时 allow_loopback 默认 False (保持 SSRF 守卫)。"""
    import isac.dispatch as dispatch_mod

    seen: dict = {}

    async def _fake_download(message, store, *, http_client=None, allow_loopback=False):
        seen["allow_loopback"] = allow_loopback
        return 0

    monkeypatch.setattr(dispatch_mod, "download_inbound_media", _fake_download)

    class _FakeAgentManager:
        _services = {"uploads_store": object(), "global_config": {}}

    msg = ISACMessage(msg_id="m", platform="onebot", timestamp=0, user_id="u", user_name="u")
    await dispatch_mod._download_inbound_media_safe(msg, _FakeAgentManager())
    assert seen["allow_loopback"] is False
