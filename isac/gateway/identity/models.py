"""身份归一数据契约 (N3, MEMORY_DESIGN.md §3.1)。

跨平台身份的值对象: 平台身份 + 归一后的人物身份。均为纯数据、不含行为;
归一算法在 resolver.py。字段严格对齐设计文档。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlatformIdentity:
    """某平台上的一个账号 (MEMORY_DESIGN.md §3.1)。"""

    platform: str
    connection_id: str
    platform_user_id: str
    display_name: str = ""
    group_aliases: dict[str, str] = field(default_factory=dict)  # group_id -> 群内昵称
    first_seen: int = 0
    last_seen: int = 0


@dataclass
class PersonIdentity:
    """归一后的人物身份 (MEMORY_DESIGN.md §3.1)。

    一个人可绑定多个平台账号; 记忆按 person_id 聚合。
    """

    person_id: str
    aliases: list[str] = field(default_factory=list)
    platform_accounts: list[PlatformIdentity] = field(default_factory=list)
    verified: bool = False  # 是否人工/管理员确认
    confidence: float = 1.0  # 1.0=人工确认, <1.0=启发式归一
    created_at: int = 0
    updated_at: int = 0
