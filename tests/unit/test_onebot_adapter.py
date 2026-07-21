"""OneBot 适配器单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from isac.channel.adapters.onebot.adapter import OneBotAdapter
from isac.channel.model import ISACMessage, MessageSegment


@pytest.fixture
def config() -> dict[str, Any]:
    return {
        "host": "127.0.0.1",
        "port": 8080,
        "access_token": "test_token",
        "retry_interval": 0.1,
        "max_retries": 2,
    }


@pytest.fixture
def adapter(config: dict[str, Any]) -> OneBotAdapter:
    with patch("isac.channel.adapters.onebot.adapter.CQHttp") as mock_cqhttp:
        mock_bot = MagicMock()
        mock_cqhttp.return_value = mock_bot
        return OneBotAdapter(config)


class TestOneBotAdapterLifecycle:
    def test_platform_name(self, adapter: OneBotAdapter):
        assert adapter.platform_name == "qq"

    @pytest.mark.asyncio
    async def test_start_stop(self, adapter: OneBotAdapter):
        adapter._bot.run_task = AsyncMock()
        await adapter.start()
        assert adapter._running is True
        assert adapter._server_task is not None
        await adapter.stop()
        assert adapter._running is False
        assert adapter._server_task is None

    @pytest.mark.asyncio
    async def test_start_idempotent(self, adapter: OneBotAdapter):
        adapter._bot.run_task = AsyncMock()
        await adapter.start()
        first_task = adapter._server_task
        await adapter.start()
        assert adapter._server_task is first_task
        await adapter.stop()


class TestMessageConversion:
    def test_parse_private_text_message(self, adapter: OneBotAdapter):
        event = SimpleNamespace(
            message_id=123,
            user_id=456,
            group_id=None,
            time=1700000000,
            sender={"nickname": "Alice"},
            message=[{"type": "text", "data": {"text": "你好"}}],
        )
        msg = adapter._parse_message_event(event)
        assert msg.platform == "qq"
        assert msg.user_id == "456"
        assert msg.user_name == "Alice"
        assert msg.group_id is None
        assert msg.content == "你好"
        assert any(seg.type == "text" for seg in msg.segments)

    def test_parse_group_message_with_at_and_image(self, adapter: OneBotAdapter):
        event = SimpleNamespace(
            message_id=789,
            user_id=111,
            group_id=222,
            time=1700000001,
            sender={"nickname": "Bob", "card": "Bobby"},
            message=[
                {"type": "at", "data": {"qq": "333"}},
                {"type": "image", "data": {"url": "http://example.com/a.png"}},
            ],
        )
        msg = adapter._parse_message_event(event)
        assert msg.group_id == "222"
        assert msg.user_name == "Bobby"
        assert msg.has_at("333") is True
        assert any(seg.type == "image" for seg in msg.segments)

    def test_parse_reply_message(self, adapter: OneBotAdapter):
        event = SimpleNamespace(
            message_id=100,
            user_id=1,
            group_id=None,
            time=1700000002,
            sender={},
            message=[
                {"type": "reply", "data": {"id": "99"}},
                {"type": "text", "data": {"text": "ok"}},
            ],
        )
        msg = adapter._parse_message_event(event)
        assert msg.reply_to == "99"

    @pytest.mark.asyncio
    async def test_dispatch_calls_on_message(self, adapter: OneBotAdapter):
        callback = AsyncMock()
        adapter.on_message = callback
        msg = ISACMessage(
            msg_id="1",
            platform="qq",
            timestamp=0,
            user_id="u1",
            user_name="User",
        )
        await adapter._dispatch(msg)
        callback.assert_awaited_once_with(msg)


class TestSend:
    @pytest.mark.asyncio
    async def test_send_private_text(self, adapter: OneBotAdapter):
        adapter._bot.call_action = AsyncMock()
        msg = ISACMessage(
            msg_id="out_1",
            platform="qq",
            timestamp=0,
            user_id="123",
            user_name="User",
            content="hello",
        )
        result = await adapter.send(msg)
        assert result is True
        adapter._bot.call_action.assert_awaited_once()
        call_args = adapter._bot.call_action.call_args
        assert call_args.args[0] == "send_private_msg"

    @pytest.mark.asyncio
    async def test_send_group_with_segments(self, adapter: OneBotAdapter):
        adapter._bot.call_action = AsyncMock()
        msg = ISACMessage(
            msg_id="out_2",
            platform="qq",
            timestamp=0,
            user_id="123",
            user_name="User",
            group_id="456",
            segments=[
                MessageSegment(type="text", data={"text": "hi "}),
                MessageSegment(type="at", data={"user_id": "789"}),
            ],
        )
        result = await adapter.send(msg)
        assert result is True
        call_args = adapter._bot.call_action.call_args
        action = call_args.args[0] if call_args.args else call_args.kwargs.get("action")
        assert action == "send_group_msg"

    @pytest.mark.asyncio
    async def test_send_failure_returns_false(self, adapter: OneBotAdapter):
        from aiocqhttp import Error as CQHttpError

        adapter._bot.call_action = AsyncMock(side_effect=CQHttpError("network"))
        msg = ISACMessage(
            msg_id="out_3",
            platform="qq",
            timestamp=0,
            user_id="123",
            user_name="User",
            content="hello",
        )
        result = await adapter.send(msg)
        assert result is False


class TestEventHandlers:
    @pytest.mark.asyncio
    async def test_on_cq_message_dispatches(self, adapter: OneBotAdapter):
        callback = AsyncMock()
        adapter.on_message = callback
        event = SimpleNamespace(
            message_id=1,
            user_id=2,
            group_id=None,
            time=1700000000,
            sender={"nickname": "Test"},
            message=[{"type": "text", "data": {"text": "hi"}}],
        )
        await adapter._on_cq_message(event)
        callback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_meta_connect_resets_retry(self, adapter: OneBotAdapter):
        adapter._retry_count = 5
        event = SimpleNamespace(meta_event_type="lifecycle", sub_type="connect")
        await adapter._on_cq_meta_event(event)
        assert adapter._retry_count == 0
