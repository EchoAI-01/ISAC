"""IdentityResolver: 跨平台身份归一骨架 (N3, MEMORY_DESIGN.md §3.1)。

[框架已搭建 / scaffolding] 把不同 IM 的同一用户归一到统一 person_id 的挂接点就位,
组合既有 `UserMapper` (不改动它);真正的归一规则 (启发式匹配 + 冲突人工裁决) 与
持久化留待 N3 实现节点 (见 TODO)。骨架阶段委托 UserMapper 的现有映射, 行为不变。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.gateway.identity.models import PersonIdentity, PlatformIdentity
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.gateway.user_mapper import UserMapper

logger = get_logger(__name__)


class IdentityResolver:
    """跨平台身份归一器骨架 (组合 UserMapper)。"""

    def __init__(self, user_mapper: UserMapper | None = None) -> None:
        self._user_mapper = user_mapper

    async def resolve(self, platform: str, user_id: str, nickname: str = "") -> str | None:
        """解析 (platform, user_id) → 归一 person_id。

        TODO(N3): 在 UserMapper 的 master_id 之上做跨平台归一 (启发式 + 已绑定关系);
        骨架阶段直接委托 UserMapper.resolve 返回其 master_id, 与现有行为一致。
        """
        if self._user_mapper is None:
            return None
        profile = await self._user_mapper.resolve(platform, user_id, nickname)
        return profile.user_id

    async def bind(self, person_id: str, identity: PlatformIdentity) -> bool:
        """把一个平台账号绑定到已知 person。

        TODO(N3): 经 UserMapper.bind 落定并记录 verified/confidence; 骨架阶段委托后返回。
        """
        if self._user_mapper is None:
            return False
        await self._user_mapper.bind(person_id, identity.platform, identity.platform_user_id)
        return True

    def merge(self, primary: PersonIdentity, other: PersonIdentity) -> PersonIdentity:
        """合并两个被判定为同一人的身份。

        TODO(N3): 合并 aliases/platform_accounts, 处理 confidence; 骨架阶段返回 primary 不变。
        """
        _ = other
        return primary

    def arbitrate_conflict(self, candidates: list[PersonIdentity]) -> PersonIdentity | None:
        """多个候选身份冲突时的裁决入口。

        TODO(N3): 按 confidence/verified 排序, 低置信交人工裁决; 骨架阶段返回首个或 None。
        """
        return candidates[0] if candidates else None
