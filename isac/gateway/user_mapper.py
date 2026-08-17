"""UserMapper: 跨平台用户映射。

同一用户在不同平台的 user_id 映射到同一个主用户 ID (UserProfile)。

Q1: SQLite 写穿持久化落地 —— master_id (person_id) 跨重启稳定, 人物画像/记忆
按归一身份聚合才有意义。构造时不传 db_path 保持纯内存 (测试/旧调用方零行为
变化); 传入 db_path 时惰性建表, 每次 resolve 写穿 (best-effort, 持久化失败不
阻塞消息流)。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from isac.gateway.models import UserProfile
from isac.utils.helpers import new_id, unix_now
from isac.utils.logger import get_logger

logger = get_logger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS user_bindings (
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    master_id TEXT NOT NULL,
    PRIMARY KEY (platform, platform_user_id)
);
CREATE INDEX IF NOT EXISTS idx_bindings_master ON user_bindings(master_id);
CREATE TABLE IF NOT EXISTS user_profiles (
    master_id TEXT PRIMARY KEY,
    nickname TEXT,
    behavior_patterns TEXT,
    first_seen INTEGER,
    last_seen INTEGER
);
"""


class UserMapper:
    """跨平台用户映射 (内存缓存 + 可选 SQLite 写穿持久化)。"""

    def __init__(self, db_path: str | None = None) -> None:
        self._by_platform: dict[tuple[str, str], str] = {}  # (platform, user_id) -> master_id
        self._profiles: dict[str, UserProfile] = {}
        self._db_path = db_path
        self._schema_ready = False
        # MVP-Fix: resolve 的 "查缓存 → 查库 → 创建" 之间有 await (DB 读),
        # P0 并发化后不同会话的消息真并行, 同一用户首次在两个会话同时出现会
        # 各自走完未命中分支, 创建两个 master_id → 身份分裂 (画像/记忆按归一
        # 身份聚合的前提被破坏)。用锁把这段临界区串行化。
        self._resolve_lock = asyncio.Lock()

    async def resolve(self, platform: str, user_id: str, nickname: str = "") -> UserProfile:
        """解析平台用户 → 主用户画像。首次见到自动创建。

        Q1: 内存缓存未命中时先查 SQLite (重启后恢复既有 master_id), 仍未命中才
        创建新身份; 每次 resolve 写穿 last_seen/nickname (best-effort)。
        MVP-Fix: 整段 check-then-create 在 `_resolve_lock` 内串行, 消除并发
        首次接触同一用户时的身份分裂 (TOCTOU)。
        """
        key = (platform, user_id)
        async with self._resolve_lock:
            master_id = self._by_platform.get(key)
            if master_id is None:
                master_id = await self._load_from_db(platform, user_id)
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
            await self._persist(platform, user_id, profile)
            return profile

    async def bind(self, master_id: str, platform: str, user_id: str) -> None:
        """手动绑定平台账号到主用户。"""
        self._by_platform[(platform, user_id)] = master_id
        profile = self._profiles[master_id]
        profile.platform_ids[platform] = user_id
        await self._persist(platform, user_id, profile)

    async def get(self, master_id: str) -> UserProfile | None:
        profile = self._profiles.get(master_id)
        if profile is not None or self._db_path is None:
            return profile
        return await self._load_profile_row(master_id)

    # ── SQLite 写穿持久化 (Q1) ──────────────────────────────

    async def _ensure_schema(self) -> None:
        if self._db_path is None or self._schema_ready:
            return
        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            # U0 顺带批清: WAL + busy_timeout (对齐 metadata.py 既有做法)。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.executescript(SCHEMA_SQL)
            await db.commit()
        self._schema_ready = True
        logger.info("UserMapper 持久化已初始化", path=self._db_path)

    async def _load_from_db(self, platform: str, user_id: str) -> str | None:
        """按平台绑定查 master_id 并把 profile 载入内存缓存; 无持久化/未命中返回 None。"""
        if self._db_path is None:
            return None
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "SELECT master_id FROM user_bindings WHERE platform = ? AND platform_user_id = ?",
                    (platform, user_id),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                master_id = str(row[0])
                await self._hydrate_profile(db, master_id)
            self._by_platform[(platform, user_id)] = master_id
            return master_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("UserMapper 持久化读取失败, 按新用户处理", error=str(exc))
            return None

    async def _hydrate_profile(self, db, master_id: str) -> None:
        """从 DB 行重建 UserProfile 进内存缓存 (含全部平台绑定)。"""
        cursor = await db.execute(
            "SELECT nickname, behavior_patterns, first_seen, last_seen FROM user_profiles WHERE master_id = ?",
            (master_id,),
        )
        profile_row = await cursor.fetchone()
        cursor = await db.execute(
            "SELECT platform, platform_user_id FROM user_bindings WHERE master_id = ?",
            (master_id,),
        )
        binding_rows = await cursor.fetchall()
        platform_ids = {str(r[0]): str(r[1]) for r in binding_rows}
        behavior_patterns: list[dict] = []
        if profile_row and profile_row[1]:
            try:
                behavior_patterns = json.loads(profile_row[1])
            except json.JSONDecodeError:
                behavior_patterns = []
        self._profiles[master_id] = UserProfile(
            user_id=master_id,
            platform_ids=platform_ids,
            nickname=str(profile_row[0] or "") if profile_row else "",
            behavior_patterns=behavior_patterns,
            first_seen=int(profile_row[2] or 0) if profile_row else 0,
            last_seen=int(profile_row[3] or 0) if profile_row else 0,
        )
        for platform, platform_user_id in platform_ids.items():
            self._by_platform[(platform, platform_user_id)] = master_id

    async def _load_profile_row(self, master_id: str) -> UserProfile | None:
        if self._db_path is None:
            return None
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await self._hydrate_profile(db, master_id)
            return self._profiles.get(master_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("UserMapper 画像读取失败", master_id=master_id, error=str(exc))
            return None

    async def _persist(self, platform: str, user_id: str, profile: UserProfile) -> None:
        """写穿绑定 + 画像 (best-effort: 持久化失败只记日志, 不阻塞消息流)。"""
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO user_bindings (platform, platform_user_id, master_id) VALUES (?, ?, ?)",
                    (platform, user_id, profile.user_id),
                )
                await db.execute(
                    "INSERT OR REPLACE INTO user_profiles "
                    "(master_id, nickname, behavior_patterns, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                    (
                        profile.user_id,
                        profile.nickname,
                        json.dumps(profile.behavior_patterns, ensure_ascii=False),
                        profile.first_seen,
                        profile.last_seen,
                    ),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("UserMapper 持久化写入失败, 已忽略", error=str(exc))
