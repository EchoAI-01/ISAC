"""统一记忆条目模型 (N1, MEMORY_DESIGN.md §4.1)。

L5 实现: 补齐 from_episode/to_episode 完整字段映射 + 新增 from_profile/to_profile
+ from_jargon/to_jargon + from_relationship/to_relationship。既有 metadata.py 的
episodes/person_profiles/jargon_entries 三表仍为权威存储, 本模块只做适配层
(读路径: 把行 dict 转成 MemoryItem; 写路径: 把 MemoryItem 转成行 dict),
不改动既有表 schema。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class MemoryType(StrEnum):
    """记忆类型 (MEMORY_DESIGN.md §4.1)。"""

    EPISODE = "episode"
    FACT = "fact"
    PROFILE = "profile"
    RELATIONSHIP = "relationship"
    JARGON = "jargon"
    PREFERENCE = "preference"
    SELF = "self"


class MemoryScope(StrEnum):
    """记忆作用域 / 命名空间 (MEMORY_DESIGN.md §2.1)。"""

    AGENT_PRIVATE = "agent_private"
    AGENT_GROUP = "agent_group"
    USER_GLOBAL = "user_global"
    CONVERSATION = "conversation"
    CHANNEL_GROUP = "channel_group"
    ORGANIZATION = "organization"
    SYSTEM_GLOBAL = "system_global"


# MemoryHit.hit_type → MemoryType 映射; 未知类型默认 EPISODE (兼容性兜底)。
_HIT_TYPE_TO_MEMORY_TYPE: dict[str, MemoryType] = {
    "episode": MemoryType.EPISODE,
    "paragraph": MemoryType.EPISODE,  # 段落视为 episode 子类
    "person_fact": MemoryType.PROFILE,  # 人物事实视为 profile 子类
    "profile": MemoryType.PROFILE,
    "jargon": MemoryType.JARGON,
    "relationship": MemoryType.RELATIONSHIP,
    "fact": MemoryType.FACT,
}


@dataclass
class MemoryItem:
    """统一记忆条目 (MEMORY_DESIGN.md §4.1)。

    所有记忆类型的统一载体; N1 落地后 storage/pipeline/injector 围绕它读写。
    """

    id: str
    agent_id: str
    scope: MemoryScope
    subject_id: str  # person_id | session_id | group_id | agent_id
    content: str
    memory_type: MemoryType
    source_message_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0
    importance: float = 0.0
    created_at: int = 0
    updated_at: int = 0
    expires_at: int | None = None
    frozen: bool = False  # 治理: 冻结 (不再更新)
    protected: bool = False  # 治理: 保护 (不被自动清理/覆盖)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_episode(cls, row: dict) -> MemoryItem:
        """把 episodes 表的一行 (dict) 适配为 MemoryItem。

        N1: 完整字段映射; summary/topics/participants/emotion/session_id/group_id 进
        metadata (episodes 表无对应列, 但 MemoryItem 需要这些信息统一注入器消费)。
        """
        return cls(
            id=str(row.get("id", "")),
            agent_id=str(row.get("agent_id", "")),
            scope=MemoryScope.AGENT_PRIVATE,
            subject_id=str(row.get("user_id", "") or row.get("session_id", "")),
            content=str(row.get("content", "")),
            memory_type=MemoryType.EPISODE,
            importance=float(row.get("importance", 0.0) or 0.0),
            created_at=int(row.get("created_at", 0) or 0),
            updated_at=int(row.get("updated_at", 0) or 0),
            metadata={
                "session_id": str(row.get("session_id", "")),
                "group_id": str(row.get("group_id", "") or ""),
                "summary": str(row.get("summary", "") or ""),
                "topics": row.get("topics", ""),
                "participants": row.get("participants", ""),
                "emotion": str(row.get("emotion", "") or ""),
            },
        )

    def to_episode(self) -> dict:
        """把 MemoryItem 反向映射为 episodes 行 (供写回)。

        N1: 与 from_episode 对称; metadata 里的字段还原成 episodes 列。
        """
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "session_id": str(self.metadata.get("session_id", "")),
            "user_id": self.subject_id,
            "content": self.content,
            "summary": str(self.metadata.get("summary", "") or ""),
            "topics": self.metadata.get("topics", ""),
            "participants": self.metadata.get("participants", ""),
            "emotion": str(self.metadata.get("emotion", "") or ""),
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at or self.created_at,
            "group_id": str(self.metadata.get("group_id", "") or ""),
        }

    @classmethod
    def from_profile(cls, row: dict) -> MemoryItem:
        """把 person_profiles 表的一行适配为 MemoryItem。

        N1: scope=USER_GLOBAL (跨 IM 用户画像); subject_id=person_id;
        content=profile_text; name/traits/relationship_depth 等进 metadata。
        """
        return cls(
            id=f"{row.get('agent_id', '')}:{row.get('person_id', '')}",
            agent_id=str(row.get("agent_id", "")),
            scope=MemoryScope.USER_GLOBAL,
            subject_id=str(row.get("person_id", "")),
            content=str(row.get("profile_text", "") or ""),
            memory_type=MemoryType.PROFILE,
            created_at=int(row.get("first_seen", 0) or 0),
            updated_at=int(row.get("last_seen", 0) or 0),
            metadata={
                "name": str(row.get("name", "") or ""),
                "traits": row.get("traits", ""),
                "relationship_depth": float(row.get("relationship_depth", 0.0) or 0.0),
                "interaction_count": int(row.get("interaction_count", 0) or 0),
                "first_seen": int(row.get("first_seen", 0) or 0),
                "last_seen": int(row.get("last_seen", 0) or 0),
                "embedding_hash": str(row.get("embedding_hash", "") or ""),
            },
        )

    def to_profile(self) -> dict:
        """把 MemoryItem 反向映射为 person_profiles 行。"""
        return {
            "agent_id": self.agent_id,
            "person_id": self.subject_id,
            "name": str(self.metadata.get("name", "") or ""),
            "profile_text": self.content,
            "traits": self.metadata.get("traits", ""),
            "relationship_depth": float(self.metadata.get("relationship_depth", 0.0) or 0.0),
            "interaction_count": int(self.metadata.get("interaction_count", 0) or 0),
            "first_seen": int(self.metadata.get("first_seen", 0) or 0),
            "last_seen": int(self.metadata.get("last_seen", self.created_at) or 0),
            "embedding_hash": str(self.metadata.get("embedding_hash", "") or ""),
        }

    @classmethod
    def from_jargon(cls, row: dict) -> MemoryItem:
        """把 jargon_entries 表的一行适配为 MemoryItem。

        N1: scope=AGENT_PRIVATE (黑话 Agent 私有); subject_id=agent_id;
        content=meaning; word/context/usage_count 进 metadata。
        """
        return cls(
            id=f"{row.get('agent_id', '')}:{row.get('word', '')}",
            agent_id=str(row.get("agent_id", "")),
            scope=MemoryScope.AGENT_PRIVATE,
            subject_id=str(row.get("agent_id", "")),  # jargon 是 Agent 私有
            content=str(row.get("meaning", "") or ""),
            memory_type=MemoryType.JARGON,
            created_at=int(row.get("created_at", 0) or 0),
            metadata={
                "word": str(row.get("word", "") or ""),
                "context": str(row.get("context", "") or ""),
                "usage_count": int(row.get("usage_count", 0) or 0),
            },
        )

    def to_jargon(self) -> dict:
        """把 MemoryItem 反向映射为 jargon_entries 行。"""
        return {
            "agent_id": self.agent_id,
            "word": str(self.metadata.get("word", "") or ""),
            "meaning": self.content,
            "context": str(self.metadata.get("context", "") or ""),
            "usage_count": int(self.metadata.get("usage_count", 0) or 0),
            "created_at": self.created_at,
        }

    @classmethod
    def from_relationship(cls, row: dict) -> MemoryItem:
        """把 relationship 行 (HUMANLIKE_RUNTIME.md §6.1 RelationshipState) 适配为 MemoryItem。

        N1: scope=USER_GLOBAL; subject_id=person_id; content=关系描述;
        memory_type=RELATIONSHIP; relationship_depth/familiarity/trust 进 metadata。
        """
        return cls(
            id=f"{row.get('agent_id', '')}:{row.get('person_id', '')}:rel",
            agent_id=str(row.get("agent_id", "")),
            scope=MemoryScope.USER_GLOBAL,
            subject_id=str(row.get("person_id", "")),
            content=str(row.get("description", "") or ""),
            memory_type=MemoryType.RELATIONSHIP,
            metadata={
                "relationship_depth": float(row.get("relationship_depth", 0.0) or 0.0),
                "familiarity": float(row.get("familiarity", 0.0) or 0.0),
                "trust": float(row.get("trust", 0.0) or 0.0),
                "interaction_count": int(row.get("interaction_count", 0) or 0),
                "last_interaction_at": int(row.get("last_interaction_at", 0) or 0),
            },
        )

    def to_relationship(self) -> dict:
        """把 MemoryItem 反向映射为 relationship 行。"""
        return {
            "agent_id": self.agent_id,
            "person_id": self.subject_id,
            "description": self.content,
            "relationship_depth": float(self.metadata.get("relationship_depth", 0.0) or 0.0),
            "familiarity": float(self.metadata.get("familiarity", 0.0) or 0.0),
            "trust": float(self.metadata.get("trust", 0.0) or 0.0),
            "interaction_count": int(self.metadata.get("interaction_count", 0) or 0),
            "last_interaction_at": int(self.metadata.get("last_interaction_at", 0) or 0),
        }
