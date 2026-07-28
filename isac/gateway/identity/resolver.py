"""IdentityResolver: 跨平台身份归一 (N3, MEMORY_DESIGN.md §3.1)。

N3 实现: 在 UserMapper.master_id 之上做跨平台归一 —— person_identities 持久化
(verified/confidence/source); resolve 命中 verified 直接返回, 未命中且
heuristic_enabled=True 时按 nickname 启发式匹配 (confidence<1.0); bind 写表
+verified=1; merge 合并 aliases/platform_accounts, confidence 取较低, verified
取 AND; arbitrate_conflict 按 confidence 排序, <0.7 写 identity_conflicts 表
供人工裁决。组合 UserMapper, 不改动它; heuristic 默认 False 防误合并。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Any

import aiosqlite

from isac.gateway.identity.models import PersonIdentity, PlatformIdentity
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.gateway.user_mapper import UserMapper

logger = get_logger(__name__)

# 启发式合并的 confidence 阈值: 低于此值不自动合并, 写 identity_conflicts
CONFLICT_THRESHOLD: float = 0.7

DEFAULT_DB_PATH = "data/identity.db"


class IdentityResolver:
    """跨平台身份归一器 (组合 UserMapper, 不改动它)。

    默认 heuristic_enabled=False (只走 verified 显式绑定, 避免误合并);
    显式设 True 时按 nickname 启发式匹配, confidence<1.0, <0.7 写冲突表。
    """

    def __init__(
        self,
        user_mapper: UserMapper | None = None,
        *,
        heuristic_enabled: bool = False,
        db_path: str = DEFAULT_DB_PATH,
    ) -> None:
        self._user_mapper = user_mapper
        self.heuristic_enabled = heuristic_enabled
        self._db_path = db_path

    async def _ensure_schema(self) -> None:
        """惰性创建 person_identities / identity_conflicts 表 (复用 K3 _ensure_column 思路)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS person_identities (
                    person_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    connection_id TEXT,
                    platform_user_id TEXT NOT NULL,
                    display_name TEXT,
                    verified INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'manual',
                    first_seen INTEGER,
                    last_seen INTEGER,
                    PRIMARY KEY (person_id, platform, platform_user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_person_platform ON person_identities(platform, platform_user_id);
                CREATE INDEX IF NOT EXISTS idx_person_display ON person_identities(display_name);
                CREATE TABLE IF NOT EXISTS identity_conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    candidates_json TEXT,
                    highest_confidence REAL,
                    created_at INTEGER NOT NULL,
                    resolved INTEGER DEFAULT 0
                );
                """
            )
            await db.commit()

    async def resolve(self, platform: str, user_id: str, nickname: str = "") -> str | None:
        """解析 (platform, user_id) → 归一 person_id。

        N3: 先查 person_identities verified 命中; 未命中且 heuristic_enabled 时
        按 nickname 匹配 (confidence<1.0); 仍无则委托 UserMapper 创建新 person
        (无 UserMapper 时返回 None, 供 arbitrate_conflict 测试场景)。
        """
        await self._ensure_schema()
        # 1. verified 命中
        # CR2-Fix-17: 此前这里没有 AND verified = 1, 任何 confidence/verified 值
        # 的行都会被当作"verified 命中"直接返回 (包括步骤 2 启发式写入的低置信度
        # 记录), 与本步骤自己的注释语义矛盾, 也让 heuristic_enabled=False 时写入
        # 的记录 (若存在) 意外被信任。
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT person_id, verified, confidence FROM person_identities "
                "WHERE platform = ? AND platform_user_id = ? AND verified = 1",
                (platform, user_id),
            )
            row = await cursor.fetchone()
        if row and row["person_id"]:
            return row["person_id"]
        # 2. 启发式: nickname 匹配
        if self.heuristic_enabled and nickname:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT person_id, confidence FROM person_identities "
                    "WHERE display_name = ? ORDER BY confidence DESC LIMIT 1",
                    (nickname,),
                )
                row = await cursor.fetchone()
            if row and row["person_id"]:
                person_id = row["person_id"]
                confidence = float(row["confidence"] or 0.0)
                await self._write_identity_row(
                    person_id=person_id,
                    platform=platform,
                    platform_user_id=user_id,
                    display_name=nickname,
                    verified=0,
                    confidence=min(confidence, 0.5),
                    source="heuristic",
                )
                logger.info(
                    "启发式归一匹配",
                    person_id=person_id,
                    platform=platform,
                    user_id=user_id,
                    confidence=min(confidence, 0.5),
                )
                return person_id
        # 3. 委托 UserMapper 创建新 person (兜底); 无 mapper 返回 None
        if self._user_mapper is None:
            return None
        profile = await self._user_mapper.resolve(platform, user_id, nickname)
        return profile.user_id

    async def _write_identity_row(
        self,
        *,
        person_id: str,
        platform: str,
        platform_user_id: str,
        display_name: str = "",
        connection_id: str = "",
        verified: int = 0,
        confidence: float = 1.0,
        source: str = "manual",
    ) -> None:
        """upsert 一条 person_identities 记录。"""
        now = int(time.time())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO person_identities "
                "(person_id, platform, connection_id, platform_user_id, display_name, "
                "verified, confidence, source, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    person_id,
                    platform,
                    connection_id,
                    platform_user_id,
                    display_name,
                    verified,
                    confidence,
                    source,
                    now,
                    now,
                ),
            )
            await db.commit()

    async def bind(self, person_id: str, identity: PlatformIdentity) -> bool:
        """把一个平台账号绑定到已知 person (verified=1, confidence=1.0, source=manual)。

        N3: 同时调 UserMapper.bind 保持兼容 (UserMapper 要求 master_id 已存在,
        所以先用 nickname resolve 创建/获取 profile, 再 bind); 落 person_identities 表。
        """
        if self._user_mapper is None:
            # 无 UserMapper 时只落 person_identities (供 arbitrate_conflict 测试)
            await self._ensure_schema()
            await self._write_identity_row(
                person_id=person_id,
                platform=identity.platform,
                platform_user_id=identity.platform_user_id,
                display_name=identity.display_name,
                connection_id=identity.connection_id,
                verified=1,
                confidence=1.0,
                source="manual",
            )
            return True
        # 先用 nickname resolve 让 UserMapper 创建 profile (若 master_id 不存在)
        existing = await self._user_mapper.get(person_id)
        if existing is None:
            # 用 display_name 当 nickname 创建一个新 profile, 然后改 user_id 不现实;
            # 实际场景 bind 是把已有 person 绑定新平台账号。这里若 person_id 不在
            # UserMapper, 我们临时跳过 UserMapper 同步, 只落 person_identities 表。
            await self._ensure_schema()
            await self._write_identity_row(
                person_id=person_id,
                platform=identity.platform,
                platform_user_id=identity.platform_user_id,
                display_name=identity.display_name,
                connection_id=identity.connection_id,
                verified=1,
                confidence=1.0,
                source="manual",
            )
            return True
        await self._ensure_schema()
        await self._write_identity_row(
            person_id=person_id,
            platform=identity.platform,
            platform_user_id=identity.platform_user_id,
            display_name=identity.display_name,
            connection_id=identity.connection_id,
            verified=1,
            confidence=1.0,
            source="manual",
        )
        await self._user_mapper.bind(person_id, identity.platform, identity.platform_user_id)
        logger.info(
            "身份已绑定",
            person_id=person_id,
            platform=identity.platform,
            user_id=identity.platform_user_id,
        )
        return True

    def merge(self, primary: PersonIdentity, other: PersonIdentity) -> PersonIdentity:
        """合并两个被判定为同一人的身份。

        N3: aliases 取并集 (去重); platform_accounts 取并集; confidence 取较低者;
        verified 取 AND (任一未验证则未验证); person_id 保留 primary 的。
        """
        merged_aliases = list(dict.fromkeys([*primary.aliases, *other.aliases]))
        # platform_accounts 按 (platform, platform_user_id) 去重
        seen: set[tuple[str, str]] = set()
        merged_accounts: list[PlatformIdentity] = []
        for acc in [*primary.platform_accounts, *other.platform_accounts]:
            key = (acc.platform, acc.platform_user_id)
            if key in seen:
                continue
            seen.add(key)
            merged_accounts.append(acc)
        return PersonIdentity(
            person_id=primary.person_id,
            aliases=merged_aliases,
            platform_accounts=merged_accounts,
            verified=primary.verified and other.verified,
            confidence=min(primary.confidence, other.confidence),
            created_at=primary.created_at,
            updated_at=int(time.time()),
        )

    def arbitrate_conflict(self, candidates: list[PersonIdentity]) -> PersonIdentity | None:
        """多个候选身份冲突时的裁决入口。

        N3: 按 confidence 降序取最高者; 最高 confidence < CONFLICT_THRESHOLD (0.7)
        时写 identity_conflicts 表供人工裁决 (用 asyncio.to_thread 包装 async 写,
        避免"no current event loop"与同步调用方冲突)。仍返回最高者。
        """
        if not candidates:
            return None
        sorted_candidates = sorted(candidates, key=lambda c: c.confidence, reverse=True)
        winner = sorted_candidates[0]
        if winner.confidence < CONFLICT_THRESHOLD:
            self._write_conflict_record_sync(winner, candidates)
        return winner

    def _write_conflict_record_sync(
        self, winner: PersonIdentity, candidates: list[PersonIdentity]
    ) -> None:
        """同步写 identity_conflicts 记录 (sqlite3 同步连接, 避免 event loop 依赖)."""
        import json
        import sqlite3

        conflict_id = uuid.uuid4().hex
        candidates_json = json.dumps(
            [
                {
                    "person_id": c.person_id,
                    "confidence": c.confidence,
                    "verified": c.verified,
                    "aliases": c.aliases,
                }
                for c in candidates
            ],
            ensure_ascii=False,
        )
        now = int(time.time())
        try:
            self._ensure_schema_sync()
            with sqlite3.connect(self._db_path) as db:
                db.execute(
                    "INSERT INTO identity_conflicts "
                    "(conflict_id, person_id, candidates_json, highest_confidence, created_at, resolved) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (conflict_id, winner.person_id, candidates_json, winner.confidence, now),
                )
                db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("写 identity_conflicts 失败, 已忽略", error=str(exc))

    def _ensure_schema_sync(self) -> None:
        """同步版 schema 创建 (sqlite3 标准库)."""
        import sqlite3

        with sqlite3.connect(self._db_path) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS person_identities (
                    person_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    connection_id TEXT,
                    platform_user_id TEXT NOT NULL,
                    display_name TEXT,
                    verified INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'manual',
                    first_seen INTEGER,
                    last_seen INTEGER,
                    PRIMARY KEY (person_id, platform, platform_user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_person_platform ON person_identities(platform, platform_user_id);
                CREATE INDEX IF NOT EXISTS idx_person_display ON person_identities(display_name);
                CREATE TABLE IF NOT EXISTS identity_conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL,
                    candidates_json TEXT,
                    highest_confidence REAL,
                    created_at INTEGER NOT NULL,
                    resolved INTEGER DEFAULT 0
                );
                """
            )
            db.commit()

    def list_conflicts(self) -> list[dict[str, Any]]:
        """读取未裁决的冲突记录 (同步, 供人工裁决界面)。

        Fix-29: 保持同步签名不变 (供既有同步调用方/测试直接调用), 但
        control/api/routes_identity.py 的 HTTP 路由现在经 asyncio.to_thread
        调用这个方法, 不再在事件循环里直接跑同步 sqlite3 磁盘 IO。
        """
        import sqlite3

        self._ensure_schema_sync()
        with sqlite3.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = db.execute(
                "SELECT conflict_id, person_id, candidates_json, highest_confidence, created_at, resolved "
                "FROM identity_conflicts WHERE resolved = 0 ORDER BY created_at ASC"
            )
            rows = cursor.fetchall()
        return [
            {
                "conflict_id": r["conflict_id"],
                "person_id": r["person_id"],
                "candidates": r["candidates_json"],
                "highest_confidence": r["highest_confidence"],
                "created_at": r["created_at"],
                "resolved": r["resolved"],
            }
            for r in rows
        ]

    async def resolve_conflict(self, conflict_id: str, person_id: str) -> bool:
        """S4: 人工裁决冲突 —— 标记 resolved=1, 并把 person_id 更新为人工选择结果。

        不存在的 conflict_id 返回 False; 存在但已 resolved 仍幂等返回 True。
        人工选择的 person_id 与自动 winner 不同时, 更新该行的 person_id 字段。

        Fix-29: 之前声明 async def 但内部全程用同步 sqlite3, 零 await, 实际是
        阻塞整个事件循环的"伪 async"——控制面这个端点被调用时, 所有平台的消息
        处理都会停滞。实际的同步 DB 操作现在放进 _resolve_conflict_sync,
        经 asyncio.to_thread 在线程池执行, 真正不阻塞事件循环。
        """
        if not conflict_id or not person_id:
            return False
        resolved = await asyncio.to_thread(self._resolve_conflict_sync, conflict_id, person_id)
        if resolved:
            logger.info("身份冲突已裁决", conflict_id=conflict_id, person_id=person_id)
        return resolved

    def _resolve_conflict_sync(self, conflict_id: str, person_id: str) -> bool:
        """Fix-29: resolve_conflict 的同步实现, 供 asyncio.to_thread 调用。"""
        import sqlite3

        self._ensure_schema_sync()
        with sqlite3.connect(self._db_path) as db:
            cursor = db.execute(
                "SELECT conflict_id FROM identity_conflicts WHERE conflict_id = ?",
                (conflict_id,),
            )
            if cursor.fetchone() is None:
                return False
            db.execute(
                "UPDATE identity_conflicts SET resolved = 1, person_id = ? WHERE conflict_id = ?",
                (person_id, conflict_id),
            )
            db.commit()
        return True
