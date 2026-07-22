"""H1 平台适配器测试 - Telegram/WebChat/Discord 消息转换。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from isac.channel.adapters.discord.adapter import DiscordAdapter
from isac.channel.adapters.telegram.adapter import TelegramAdapter
from isac.channel.adapters.webchat.adapter import WebChatAdapter
from isac.channel.model import ISACMessage


class _MockHTTPClient:
    """通用 HTTP mock, 记录调用 + 按预设返回。"""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.responses = responses or {}
        self._closed = False

    async def request(self, method: str, url: str, **kwargs) -> Any:
        self.calls.append((method, url, kwargs))
        # url 匹配 responses key
        for key, value in self.responses.items():
            if key in url:
                return _MockResponse(value)
        return _MockResponse({"ok": True, "result": {}})

    async def post(self, url: str, **kwargs) -> Any:
        return await self.request("POST", url, **kwargs)

    async def aclose(self) -> None:
        self._closed = True


class _MockResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self) -> Any:
        return self._payload


class TestTelegramAdapter:
    def test_platform_name(self) -> None:
        adapter = TelegramAdapter({"bot_token": "fake"})
        assert adapter.platform_name == "telegram"

    @pytest.mark.asyncio
    async def test_to_isac_message_converts_private_chat(self) -> None:
        adapter = TelegramAdapter({"bot_token": "fake"})
        tg_msg = {
            "message_id": 123,
            "date": 1700000000,
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200, "username": "alice", "first_name": "Alice"},
            "text": "hello",
        }
        msg = adapter._to_isac_message(tg_msg)
        assert msg is not None
        assert msg.msg_id == "123"
        assert msg.user_id == "200"
        assert msg.user_name == "alice"
        assert msg.group_id is None  # 私聊
        assert msg.content == "hello"

    @pytest.mark.asyncio
    async def test_to_isac_message_converts_group_chat(self) -> None:
        adapter = TelegramAdapter({"bot_token": "fake"})
        tg_msg = {
            "message_id": 456,
            "date": 1700000000,
            "chat": {"id": -100123, "type": "supergroup"},
            "from": {"id": 200, "username": "bob"},
            "text": "hi group",
        }
        msg = adapter._to_isac_message(tg_msg)
        assert msg is not None
        assert msg.group_id == "-100123"  # 群组
        assert msg.content == "hi group"

    @pytest.mark.asyncio
    async def test_send_uses_chat_id_from_group_or_user(self) -> None:
        adapter = TelegramAdapter({"bot_token": "fake"})
        adapter._http_client = _MockHTTPClient()
        msg = ISACMessage(
            msg_id="",
            platform="telegram",
            timestamp=0,
            user_id="user_200",
            user_name="",
            group_id=None,
            content="reply",
        )
        result = await adapter.send(msg)
        assert result is True
        assert len(adapter._http_client.calls) == 1

    @pytest.mark.asyncio
    async def test_start_without_token_raises(self) -> None:
        adapter = TelegramAdapter({})
        with pytest.raises(RuntimeError, match="bot_token"):
            await adapter.start()


class TestWebChatAdapter:
    def test_platform_name(self) -> None:
        adapter = WebChatAdapter({})
        assert adapter.platform_name == "webchat"

    @pytest.mark.asyncio
    async def test_send_queues_reply_for_session(self) -> None:
        adapter = WebChatAdapter({})
        msg = ISACMessage(
            msg_id="",
            platform="webchat",
            timestamp=0,
            user_id="user_1",
            user_name="",
            content="Bot 回复",
            session_id="sess_1",
        )
        result = await adapter.send(msg)
        assert result is True
        replies = await adapter.poll_replies("sess_1")
        assert len(replies) == 1
        assert replies[0]["content"] == "Bot 回复"

    @pytest.mark.asyncio
    async def test_poll_replies_returns_empty_after_consume(self) -> None:
        adapter = WebChatAdapter({})
        msg = ISACMessage(
            msg_id="",
            platform="webchat",
            timestamp=0,
            user_id="u1",
            user_name="",
            content="reply 1",
            session_id="s1",
        )
        await adapter.send(msg)
        replies = await adapter.poll_replies("s1")
        assert len(replies) == 1
        # 再次 poll 应为空
        replies = await adapter.poll_replies("s1")
        assert replies == []

    @pytest.mark.asyncio
    async def test_receive_from_client_triggers_on_message(self) -> None:
        adapter = WebChatAdapter({})
        received: list[ISACMessage] = []

        async def on_message(msg: ISACMessage) -> None:
            received.append(msg)

        adapter.on_message = on_message
        await adapter.receive_from_client("sess_x", "user_1", "hello from client")
        assert len(received) == 1
        assert received[0].content == "hello from client"
        assert received[0].platform == "webchat"


class TestDiscordAdapter:
    def test_platform_name(self) -> None:
        adapter = DiscordAdapter({"bot_token": "fake"})
        assert adapter.platform_name == "discord"

    @pytest.mark.asyncio
    async def test_to_isac_message_converts_group_message(self) -> None:
        adapter = DiscordAdapter({"bot_token": "fake"})
        dc_msg = {
            "id": "999",
            "timestamp": "2024-01-01T12:00:00.000000+00:00",
            "author": {"id": "200", "username": "alice"},
            "content": "hello discord",
        }
        msg = adapter._to_isac_message(dc_msg, "channel_123")
        assert msg is not None
        assert msg.msg_id == "999"
        assert msg.user_id == "200"
        assert msg.user_name == "alice"
        assert msg.group_id == "channel_123"
        assert msg.content == "hello discord"

    @pytest.mark.asyncio
    async def test_start_without_token_raises(self) -> None:
        adapter = DiscordAdapter({})
        with pytest.raises(RuntimeError, match="bot_token"):
            await adapter.start()

    @pytest.mark.asyncio
    async def test_send_posts_to_channel_endpoint(self) -> None:
        adapter = DiscordAdapter({"bot_token": "fake"})
        adapter._http_client = _MockHTTPClient()
        msg = ISACMessage(
            msg_id="",
            platform="discord",
            timestamp=0,
            user_id="user_200",
            user_name="",
            group_id="channel_123",
            content="reply",
        )
        result = await adapter.send(msg)
        assert result is True
        assert len(adapter._http_client.calls) == 1
        method, url, kwargs = adapter._http_client.calls[0]
        assert "channels/channel_123/messages" in url
