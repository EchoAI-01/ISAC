"""统一消息模型 (SPECIFICATION.md 1.1)。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MessageSegment:
    """消息分段 (用于富媒体)"""

    type: str  # "text" | "image" | "at" | "reply" | "emoji" | "voice"
    data: dict  # 分段内容


@dataclass
class ISACMessage:
    """跨平台统一消息模型"""

    # 基础信息
    msg_id: str  # 消息 ID
    platform: str  # 平台标识 ("qq", "telegram", ...)
    timestamp: int  # 消息时间戳 (Unix)

    # 用户信息
    user_id: str  # 平台内用户 ID
    user_name: str  # 用户昵称 (可读)
    group_id: str | None = None  # 群聊 ID (私聊为 None)
    group_name: str | None = None  # 群聊名称

    # 内容
    content: str = ""  # 纯文本内容
    segments: list[MessageSegment] = field(default_factory=list)  # 富媒体分段

    # 会话
    session_id: str = ""  # 全局统一会话 ID (由 SessionManager 分配)
    reply_to: str | None = None  # 回复的目标消息 ID

    # 元数据
    metadata: dict = field(default_factory=dict)  # 平台特定元数据

    @property
    def is_private_chat(self) -> bool:
        """是否私聊消息 (group_id 为 None)。"""
        return self.group_id is None

    def has_at(self, bot_id: str) -> bool:
        """消息中是否 @ 了指定用户 (通常传 bot 自身 ID)。"""
        return any(seg.type == "at" and seg.data.get("user_id") == bot_id for seg in self.segments)

    def has_mention(self, names: list[str]) -> bool:
        """消息文本中是否以纯文本形式提及指定名称（不含 @）。

        用于私聊场景下的门控强制触发：用户直接叫 Bot 名字也算 "提及"。
        """
        if not self.content or not names:
            return False
        lower = self.content.lower()
        return any(name.lower() in lower for name in names if name)
