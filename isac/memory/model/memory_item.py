"""统一记忆条目模型 (N1, MEMORY_DESIGN.md §4.1)。

[框架已搭建 / scaffolding] 契约就位: 把 episode/profile/jargon 等分散记忆统一到一个
`MemoryItem` (类型 + 载荷 + 元数据 + 命名空间)。真实的存储层适配与迁移 (让检索/注入
围绕 MemoryItem 展开) 留待 N1 实现节点 (见 TODO)。既有 metadata.py 的
episodes/person_profiles/jargon_entries 三表仍为权威, 本模块不改动它们。
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

        TODO(N1): 存储层迁移时补齐 profile/jargon/relationship 的适配, 并处理
        scope 推断与 source_message_ids 回填。骨架阶段只映射已知列, 不落库。
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
        )

    def to_episode(self) -> dict:
        """把 MemoryItem 反向映射为 episodes 行 (供写回)。

        TODO(N1): 与 from_episode 对称, 补齐字段与类型分派。骨架阶段仅映射已知列。
        """
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "user_id": self.subject_id,
            "content": self.content,
            "importance": self.importance,
            "created_at": self.created_at,
        }
