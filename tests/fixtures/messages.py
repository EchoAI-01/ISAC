"""测试消息工厂 (DEVELOP.md 5.4 messages.py)。"""

from __future__ import annotations

from isac.channel.model import ISACMessage, MessageSegment
from isac.utils.helpers import new_id, unix_now

BOT_ID = "bot_001"


def make_isac_message(
    content: str = "你好",
    platform: str = "qq",
    user_id: str = "user_001",
    user_name: str = "小明",
    group_id: str | None = "group_001",
    with_at: bool = False,
) -> ISACMessage:
    """构造测试消息。"""
    segments = [MessageSegment(type="text", data={"text": content})]
    if with_at:
        segments.insert(0, MessageSegment(type="at", data={"user_id": BOT_ID}))
    return ISACMessage(
        msg_id=new_id("msg"),
        platform=platform,
        timestamp=unix_now(),
        user_id=user_id,
        user_name=user_name,
        group_id=group_id,
        content=content,
        segments=segments,
    )
