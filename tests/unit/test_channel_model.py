"""channel/model 单元测试。"""

from __future__ import annotations

from isac.channel.model import ISACMessage, MessageSegment


class TestISACMessage:
    def test_has_at(self):
        msg = ISACMessage(
            msg_id="1", platform="qq", timestamp=0, user_id="u1", user_name="User",
            segments=[MessageSegment(type="at", data={"user_id": "bot_123"})],
        )
        assert msg.has_at("bot_123") is True
        assert msg.has_at("other") is False

    def test_has_mention(self):
        msg = ISACMessage(
            msg_id="1", platform="qq", timestamp=0, user_id="u1", user_name="User",
            content="ISAC，你在吗？",
        )
        assert msg.has_mention(["ISAC"]) is True
        assert msg.has_mention(["bot"]) is False
        assert msg.has_mention([]) is False

    def test_has_mention_case_insensitive(self):
        msg = ISACMessage(
            msg_id="1", platform="qq", timestamp=0, user_id="u1", user_name="User",
            content="isac 你好",
        )
        assert msg.has_mention(["ISAC"]) is True
