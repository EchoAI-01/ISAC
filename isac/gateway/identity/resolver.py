"""IdentityResolver: 跨平台身份归一 (N3, MEMORY_DESIGN.md §3.1)。

N3 实现: 在 UserMapper.master_id 之上做跨平台归一 —— person_identities 持久化
(verified/confidence/source); resolve 命中 verified 直接返回; bind 写表
+verified=1; merge 合并 aliases/platform_accounts, confidence 取较低, verified
取 AND; arbitrate_conflict 按 confidence 排序, <0.7 写 identity_conflicts 表
供人工裁决。组合 UserMapper, 不改动它; heuristic 默认 False 防误合并。

L5 (2026-10-13 review, 08-19/08-21 遗留⑤修复):
- P1-1 生产接线: resolve() 启发式路径的候选集现在经 arbitrate_conflict 单一
  裁决入口 (此前该入口零生产调用, identity_conflicts 表恒空);
- P0-2 防冒充: 昵称匹配的**证据置信度**封顶 NICKNAME_MATCH_CONFIDENCE_CAP
  (0.5) —— 恒低于 CONFLICT_THRESHOLD (0.7), 昵称撞名**永不自动归属**既有
  person (此前撞名直接返回匹配者: 攻击者改昵称即可让其消息写进对方记忆/画像);
  低置信度候选一律写冲突队列等人工裁决, 陌生人按新 person 处理 (fail-safe);
- P1-2 裁决回写: 冲突记录携带触发身份坐标 (platform/platform_user_id/
  display_name), 人工裁决后把所选 person 以 verified=1 落 person_identities
  (此后 resolve 走 verified 命中, 裁决结果真正生效 —— 此前只改 conflicts 行,
  归一行为不变)。
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
# L5/P0-2: 昵称匹配作为**证据**的置信度封顶 —— 候选行自身的 confidence 表达的是
# "该身份的验证程度", 不是"这个昵称属于这个人"的匹配强度; 昵称撞名是弱证据,
# 封顶后恒低于 CONFLICT_THRESHOLD, 永不自动归属, 一律进人工裁决队列。
NICKNAME_MATCH_CONFIDENCE_CAP: float = 0.5

DEFAULT_DB_PATH = "data/identity.db"

# identity_conflicts 的 L5 增列 (触发身份坐标, 供裁决回写)。既有库经
# _ensure_conflict_columns 惰性补列; 新库由 CREATE TABLE 直接带列。
_CONFLICT_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("platform", "TEXT"),
    ("platform_user_id", "TEXT"),
    ("display_name", "TEXT"),
)


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
            # U0 顺带批清: WAL + busy_timeout (对齐 metadata.py 既有做法)。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
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
                    resolved INTEGER DEFAULT 0,
                    platform TEXT,
                    platform_user_id TEXT,
                    display_name TEXT
                );
                """
            )
            # L5: 既有库补列 (CREATE TABLE IF NOT EXISTS 不改已存在的表)。
            for col, col_type in _CONFLICT_EXTRA_COLUMNS:
                try:
                    await db.execute(f"ALTER TABLE identity_conflicts ADD COLUMN {col} {col_type}")
                except Exception:  # noqa: BLE001 列已存在
                    pass
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
        # 2. 启发式: nickname 匹配 (L5: 候选集过裁决入口, 弱证据不自动归属)
        if self.heuristic_enabled and nickname:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT person_id, confidence, verified FROM person_identities "
                    "WHERE display_name = ? ORDER BY confidence DESC",
                    (nickname,),
                )
                rows = await cursor.fetchall()
            if rows:
                trigger = PlatformIdentity(
                    platform=platform, connection_id="", platform_user_id=user_id,
                    display_name=nickname,
                )
                # P0-2: 候选携带的是"昵称撞名"这一弱证据 —— 置信度封顶, 与候选行
                # 自身的验证程度无关 (verified 行的 confidence=1.0 说的是"那个人
                # 被验证过", 不是"这个撞名者就是那个人")。
                candidates = [
                    PersonIdentity(
                        person_id=str(r["person_id"]),
                        aliases=[nickname],
                        verified=bool(r["verified"]),
                        confidence=min(float(r["confidence"] or 0.0), NICKNAME_MATCH_CONFIDENCE_CAP),
                    )
                    for r in rows
                ]
                # P1-1: 生产接线 —— 裁决入口唯一, 低置信度写冲突队列 (带触发坐标)。
                winner = await asyncio.to_thread(self.arbitrate_conflict, candidates, trigger)
                if winner is not None and winner.confidence >= CONFLICT_THRESHOLD:
                    # 高置信度证据才自动归属 (昵称路径因封顶恒不可达; 留给未来
                    # 更强证据信号 —— 同 connection_id/群昵称交叉验证等)。
                    await self._write_identity_row(
                        person_id=winner.person_id,
                        platform=platform,
                        platform_user_id=user_id,
                        display_name=nickname,
                        verified=0,
                        confidence=winner.confidence,
                        source="heuristic",
                    )
                    logger.info(
                        "启发式归一匹配",
                        person_id=winner.person_id,
                        platform=platform,
                        user_id=user_id,
                        confidence=winner.confidence,
                    )
                    return winner.person_id
                # 弱证据: 冲突已记录 (供人工裁决), 本轮不归属 —— 走下方"新人"
                # 路径 fail-safe (陌生人按新 person 处理, 不冒充既有 person)。
                logger.info(
                    "昵称撞名置信度不足, 已入冲突队列待人工裁决",
                    platform=platform, user_id=user_id, nickname=nickname,
                    candidates=len(candidates),
                )
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

    def arbitrate_conflict(
        self,
        candidates: list[PersonIdentity],
        trigger: PlatformIdentity | None = None,
    ) -> PersonIdentity | None:
        """多个候选身份冲突时的裁决入口 (L5/P1-1: resolve 启发式路径生产接线)。

        N3: 按 confidence 降序取最高者; 最高 confidence < CONFLICT_THRESHOLD (0.7)
        时写 identity_conflicts 表供人工裁决。仍返回最高者。
        L5: trigger 携带触发裁决的身份坐标 (platform/platform_user_id/display_name)
        —— 冲突记录带上它, 人工裁决后才能把结果回写为该身份的 verified 绑定
        (P1-2); 缺省 None 保持旧签名行为 (既有调用方/测试)。
        """
        if not candidates:
            return None
        sorted_candidates = sorted(candidates, key=lambda c: c.confidence, reverse=True)
        winner = sorted_candidates[0]
        if winner.confidence < CONFLICT_THRESHOLD:
            self._write_conflict_record_sync(winner, candidates, trigger)
        return winner

    def _write_conflict_record_sync(
        self,
        winner: PersonIdentity,
        candidates: list[PersonIdentity],
        trigger: PlatformIdentity | None = None,
    ) -> None:
        """同步写 identity_conflicts 记录 (sqlite3 同步连接, 避免 event loop 依赖).

        L5: 带 trigger 坐标列 + 同触发身份去重 —— 同一 (platform, platform_user_id)
        的未裁决冲突只留一条 (每条消息都会过 resolve, 不去重会刷爆冲突队列)。
        """
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
        trigger_platform = trigger.platform if trigger is not None else None
        trigger_user_id = trigger.platform_user_id if trigger is not None else None
        trigger_display = trigger.display_name if trigger is not None else None
        try:
            self._ensure_schema_sync()
            with sqlite3.connect(self._db_path) as db:
                if trigger is not None:
                    cursor = db.execute(
                        "SELECT conflict_id FROM identity_conflicts "
                        "WHERE resolved = 0 AND platform = ? AND platform_user_id = ?",
                        (trigger_platform, trigger_user_id),
                    )
                    if cursor.fetchone() is not None:
                        return  # 同触发身份已有未裁决冲突, 不重复记录
                db.execute(
                    "INSERT INTO identity_conflicts "
                    "(conflict_id, person_id, candidates_json, highest_confidence, created_at, "
                    "resolved, platform, platform_user_id, display_name) "
                    "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)",
                    (
                        conflict_id, winner.person_id, candidates_json, winner.confidence, now,
                        trigger_platform, trigger_user_id, trigger_display,
                    ),
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
                    resolved INTEGER DEFAULT 0,
                    platform TEXT,
                    platform_user_id TEXT,
                    display_name TEXT
                );
                """
            )
            # L5: 既有库补列。
            for col, col_type in _CONFLICT_EXTRA_COLUMNS:
                try:
                    db.execute(f"ALTER TABLE identity_conflicts ADD COLUMN {col} {col_type}")
                except Exception:  # noqa: BLE001 列已存在
                    pass
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
                "SELECT conflict_id, person_id, candidates_json, highest_confidence, created_at, "
                "resolved, platform, platform_user_id, display_name "
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
                # L5: 触发身份坐标 (裁决界面展示 "谁撞了名", 也是回写定位键)。
                "platform": r["platform"] if "platform" in r.keys() else None,
                "platform_user_id": r["platform_user_id"] if "platform_user_id" in r.keys() else None,
                "display_name": r["display_name"] if "display_name" in r.keys() else None,
            }
            for r in rows
        ]

    async def resolve_conflict(self, conflict_id: str, person_id: str) -> bool:
        """S4: 人工裁决冲突 —— 标记 resolved=1 + 把所选 person 回写为触发身份的
        verified 绑定 (L5/P1-2)。

        不存在的 conflict_id 返回 False; 存在但已 resolved 仍幂等返回 True。
        回写: 冲突记录带触发坐标 (platform/platform_user_id/display_name) 时,
        把 (触发身份 → 人工所选 person_id) 以 verified=1/confidence=1.0/
        source=manual 落 person_identities —— 此后 resolve 第一步 verified 命中
        直接返回, 裁决结果真正生效 (此前只改 conflicts 行, 归一行为不变)。

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
        """Fix-29: resolve_conflict 的同步实现, 供 asyncio.to_thread 调用。

        L5/P1-2: resolved 标记 + 人工所选 person 回写 person_identities (verified)。
        """
        import sqlite3

        self._ensure_schema_sync()
        with sqlite3.connect(self._db_path) as db:
            db.row_factory = sqlite3.Row
            cursor = db.execute(
                "SELECT conflict_id, platform, platform_user_id, display_name "
                "FROM identity_conflicts WHERE conflict_id = ?",
                (conflict_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False
            db.execute(
                "UPDATE identity_conflicts SET resolved = 1, person_id = ? WHERE conflict_id = ?",
                (person_id, conflict_id),
            )
            # P1-2 回写: 触发身份 → 人工所选 person 的 verified 绑定。
            platform = row["platform"] if "platform" in row.keys() else None
            platform_user_id = row["platform_user_id"] if "platform_user_id" in row.keys() else None
            if platform and platform_user_id:
                now = int(time.time())
                db.execute(
                    "INSERT OR REPLACE INTO person_identities "
                    "(person_id, platform, connection_id, platform_user_id, display_name, "
                    "verified, confidence, source, first_seen, last_seen) "
                    "VALUES (?, ?, '', ?, ?, 1, 1.0, 'manual_arbitration', ?, ?)",
                    (
                        person_id, platform, platform_user_id,
                        row["display_name"] if "display_name" in row.keys() else "",
                        now, now,
                    ),
                )
            db.commit()
        return True
