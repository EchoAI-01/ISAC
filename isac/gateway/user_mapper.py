"""UserMapper: 跨平台用户映射。

同一用户在不同平台的 user_id 映射到同一个主用户 ID (UserProfile)。
"""

from __future__ import annotations

from isac.gateway.models import UserProfile
from isac.utils.helpers import new_id, unix_now
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class UserMapper:
    """跨平台用户映射。

    TODO(Day 7): SQLite 持久化 + 手动绑定 (用户声明/管理命令)。
    当前为内存实现。
    """

    def __init__(self) -> None:
        self._by_platform: dict[tuple[str, str], str] = {}  # (platform, user_id) -> master_id
        self._profiles: dict[str, UserProfile] = {}

    async def resolve(self, platform: str, user_id: str, nickname: str = "") -> UserProfile:
        """解析平台用户 → 主用户画像。首次见到自动创建。"""
        key = (platform, user_id)
        master_id = self._by_platform.get(key)
        if master_id is None:
            master_id = new_id("user")
            self._by_platform[key] = master_id
            profile = UserProfile(
                user_id=master_id,
                platform_ids={platform: user_id},
                nickname=nickname,
                first_seen=unix_now(),
            )
            self._profiles[master_id] = profile
            logger.info("创建用户画像", master_id=master_id, platform=platform)
        profile = self._profiles[master_id]
        profile.last_seen = unix_now()
        if nickname:
            profile.nickname = nickname
        return profile

    async def bind(self, master_id: str, platform: str, user_id: str) -> None:
        """手动绑定平台账号到主用户。"""
        self._by_platform[(platform, user_id)] = master_id
        profile = self._profiles[master_id]
        profile.platform_ids[platform] = user_id

    async def get(self, master_id: str) -> UserProfile | None:
        return self._profiles.get(master_id)
