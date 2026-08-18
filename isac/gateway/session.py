"""SessionManager: 会话查找/创建与持久化。

会话归属: Session 含 agent_id 字段 (SPECIFICATION.md 1.2)，
同一会话在不同 Agent 下是相互独立的 Session。

K7: 内存实现 + TTL 回收 + session_id 二级索引 (替代线性扫描)。
R5: 可选 SQLite 写穿 + 重启恢复 (与 Q1 的 UserMapper 持久化同构)。构造时不传
db_path 保持纯内存 (测试/旧调用方零行为变化); 传入 db_path 时惰性建表, 每次
get_or_create 写穿 (best-effort, 持久化失败不阻塞消息流), 重启后 get_or_create
未命中先查库 hydrate 既有会话 (复用 session_id 不新建), 实现"重启不丢会话"。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from isac.channel.model import ISACMessage
from isac.gateway.models import Session
from isac.utils.helpers import new_id, unix_now
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 小时无活动自动回收

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    user_id TEXT,
    agent_id TEXT,
    platform TEXT,
    group_id TEXT,
    is_group INTEGER,
    created_at INTEGER,
    last_active INTEGER,
    state TEXT,
    platform_session_id TEXT DEFAULT '',
    user_ids TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sessions_key ON sessions(session_key);
"""

# Fix-79: 既有库 (旧 schema 建表) 补列迁移 —— CREATE TABLE IF NOT EXISTS 不会
# 给已存在的表加列。muted_until 是 monotonic 运行时值, 重启后无意义, 不持久化。
_SCHEMA_MIGRATIONS: tuple[str, ...] = (
    "ALTER TABLE sessions ADD COLUMN platform_session_id TEXT DEFAULT ''",
    "ALTER TABLE sessions ADD COLUMN user_ids TEXT DEFAULT '{}'",
)


class SessionManager:
    """会话管理器。

    K7: 加 session_id 二级索引 + TTL 回收, 长期运行不内存膨胀;
    get(session_id) 由 O(N) 降为 O(1)。
    R5: 传 db_path 时 SQLite 写穿 + 重启恢复 (照 UserMapper 同构)。
    """

    def __init__(self, config: dict[str, Any] | None = None, db_path: str | None = None):
        self.config = config or {}
        self._sessions: dict[str, Session] = {}  # session_key -> Session
        self._by_id: dict[str, str] = {}  # session_id -> session_key (二级索引)
        self._ttl_seconds = int(self.config.get("session_ttl_seconds", DEFAULT_TTL_SECONDS))
        self._db_path = db_path
        self._schema_ready = False
        # R5: get_or_create 的 "查缓存 → 查库 → 创建" 之间有 await (DB 读), 并发消息
        # 流下同一会话可能双创建 session_id。用锁串行 check-then-create (照 UserMapper)。
        # Fix-78: 锁细化为 per-session_key —— 此前单一全局锁把**所有会话**的
        # check-create-写穿 (含两段 DB I/O await) 串成一条队列, 高并发多会话时
        # 每条消息都要排队等别的会话落库。per-key 锁只串行同一会话的首次创建,
        # 不同会话互不阻塞; _registry_lock 仅保护锁注册表本身 (临界区无 I/O)。
        self._registry_lock = asyncio.Lock()
        # Fix-103: 锁注册表升级为引用计数 {key: (lock, 活跃持有数)}。Fix-78 曾用
        # "会话已回收且锁空闲 (locked()==False)" 在 _gc_expired 里惰性删锁, 但
        # "_key_lock(key) 返回锁对象" 与调用方 "async with 真正拿到锁" 之间存在
        # await 空隙 —— 该时刻锁尚未被持有、会话尚未创建, 恰好满足删锁条件;
        # 另一协程随后会取到**新建的锁**, 两把锁并行导致同一会话的
        # check-then-create 失去串行, 双创建 session_id (身份分裂, 其一会被孤立)。
        # 引用计数保证: 只要有人持有锁引用 (取出到释放全程) 注册表条目绝不删除,
        # 归零即删 —— 注册表不会无界增长, 也不再依赖 _gc_expired 顺带回收。
        self._key_locks: dict[str, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def _held_key_lock(self, key: str) -> AsyncIterator[asyncio.Lock]:
        """Fix-103: 取 (惰性创建) 某 session_key 的创建锁, 引用计数防竞态回收。

        计数在注册表锁临界区内 +1 (此处无 await, 不会被插队), 退出时 -1;
        归零删除条目。锁对象从取出到释放始终在注册表有登记, 消灭了
        "已返回未持有" 窗口被 GC 的竞态。
        """
        async with self._registry_lock:
            entry = self._key_locks.get(key)
            lock = entry[0] if entry is not None else asyncio.Lock()
            refs = entry[1] if entry is not None else 0
            self._key_locks[key] = (lock, refs + 1)
        try:
            async with lock:
                yield lock
        finally:
            async with self._registry_lock:
                entry = self._key_locks.get(key)
                if entry is not None and entry[0] is lock:
                    if entry[1] <= 1:
                        del self._key_locks[key]
                    else:
                        self._key_locks[key] = (lock, entry[1] - 1)

    def make_session_key(self, agent_id: str, platform: str, user_id: str, group_id: str | None) -> str:
        """生成会话键: agent + 平台 + (群 或 用户)。"""
        target = f"group:{group_id}" if group_id else f"user:{user_id}"
        return f"{agent_id}:{platform}:{target}"

    async def get_or_create(self, message: ISACMessage, agent_id: str) -> Session:
        """查找或创建会话。

        R5: 缓存未命中时先查 SQLite (重启后恢复既有 session_id), 仍未命中才创建;
        每次 get_or_create 写穿 last_active (best-effort)。check-then-create 在
        per-key 锁内串行, 消除并发双创建。

        Fix-78: 缓存命中的热路径不再进任何锁 (此前每条消息都排全局锁); 未命中
        时只取该 session_key 的锁, 不同会话并发创建互不阻塞。last_active 更新
        与写穿移出锁 —— 同一会话并发写穿只是 last_active 后写覆盖 (同一 Session
        对象, 值等价), 无需串行。
        Fix-103: per-key 锁经 _held_key_lock 引用计数持有, 持锁期间注册表条目
        不可回收, 消灭"锁被 GC 后新来者拿到新锁"的双创建竞态。
        """
        key = self.make_session_key(agent_id, message.platform, message.user_id, message.group_id)
        session = self._sessions.get(key)
        if session is None:
            async with self._held_key_lock(key):
                session = self._sessions.get(key)
                if session is None:
                    session = await self._load_from_db(key)
                if session is None:
                    session = Session(
                        session_id=new_id("sess"),
                        user_id=message.user_id,
                        agent_id=agent_id,
                        platform=message.platform,
                        group_id=message.group_id,
                        is_group=message.group_id is not None,
                        created_at=unix_now(),
                    )
                    self._sessions[key] = session
                    self._by_id[session.session_id] = key
                    logger.info("创建会话", session_id=session.session_id, key=key)
        session.last_active = unix_now()
        message.session_id = session.session_id
        await self._persist(session, key)
        # 惰性回收: 每次 get_or_create 顺便清理过期 session (不阻塞当前会话)
        self._gc_expired()
        return session

    async def get(self, session_id: str) -> Session | None:
        """按 session_id 查找 (O(1) 二级索引)。"""
        key = self._by_id.get(session_id)
        if key is None:
            return None
        return self._sessions.get(key)

    async def list_sessions(self, *, agent_id: str | None = None) -> list[Session]:
        """列出活跃会话 (可选按 agent_id 过滤); J3-3 供 Control API。"""
        sessions = list(self._sessions.values())
        if agent_id:
            sessions = [s for s in sessions if s.agent_id == agent_id]
        return sessions

    async def close(self, session_id: str) -> None:
        """关闭并移除会话。"""
        key = self._by_id.pop(session_id, None)
        if key is None:
            return
        session = self._sessions.pop(key, None)
        if session is not None:
            session.state = "closed"
            await self._delete_from_db(session_id)

    def _gc_expired(self) -> None:
        """惰性清理 TTL 过期会话 (K7: 防止长期运行内存膨胀)。

        R5: 回收时同步删库行 (best-effort, 同步 SQLite 删用 to_thread 包装)。
        Fix-103: 此处**不再**回收 per-key 锁 —— Fix-78 的"会话没了且锁空闲就删"
        会在取锁-持锁的 await 空隙误删锁 (双创建竞态, 见 _held_key_lock 注释)。
        锁注册表改由引用计数自治: 持有者退出时归零即删, 无需惰性 GC。
        """
        if self._ttl_seconds <= 0:
            return
        cutoff = unix_now() - self._ttl_seconds
        expired_keys = [k for k, s in self._sessions.items() if s.last_active < cutoff]
        for key in expired_keys:
            session = self._sessions.pop(key, None)
            if session is not None:
                self._by_id.pop(session.session_id, None)
                logger.debug("回收过期会话", session_id=session.session_id, key=key)
                # best-effort 删库行 (同步, 失败仅记日志; gc 是惰性清理不阻塞主流程)
                if self._db_path is not None:
                    asyncio.ensure_future(self._delete_from_db(session.session_id))  # noqa: ISC003

    # ── SQLite 写穿持久化 (R5, 照 UserMapper 同构) ───────────────

    async def _ensure_schema(self) -> None:
        if self._db_path is None or self._schema_ready:
            return
        from pathlib import Path

        import aiosqlite

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            # U0 顺带批清: WAL 让并发读写不互斥 (一写多读), busy_timeout 在写锁竞争时
            # 等待而非立即 "database is locked"。对齐 metadata.py/artifacts store 的既有
            # 做法 (journal_mode 文件级持久, 一次设置后续连接继承)。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.executescript(SCHEMA_SQL)
            # Fix-79: 旧库补列 (新库列已存在, ALTER 报 duplicate column 静默跳过)
            for stmt in _SCHEMA_MIGRATIONS:
                try:
                    await db.execute(stmt)
                except Exception as exc:  # noqa: BLE001 - sqlite OperationalError (列已存在等)
                    if "duplicate column" not in str(exc).lower():
                        logger.warning("SessionManager schema 迁移跳过", stmt=stmt, error=str(exc))
            await db.commit()
        self._schema_ready = True
        logger.info("SessionManager 持久化已初始化", path=self._db_path)

    async def _load_from_db(self, session_key: str) -> Session | None:
        """按 session_key 查库并 hydrate Session 进内存; 无持久化/未命中返回 None。"""
        if self._db_path is None:
            return None
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "SELECT session_id, user_id, agent_id, platform, group_id, is_group, "
                    "created_at, last_active, state, platform_session_id, user_ids "
                    "FROM sessions WHERE session_key = ?",
                    (session_key,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                # Fix-79: 恢复 platform_session_id / user_ids —— 此前 schema 缺这两列,
                # 重启 hydrate 后出站主动消息丢失平台路由键, 只能等下一条入站消息
                # 重新填充 (重启后到用户再说话之间的主动消息发不出去)。
                try:
                    user_ids = json.loads(row[10]) if row[10] else {}
                except (ValueError, TypeError):
                    user_ids = {}
                session = Session(
                    session_id=str(row[0]),
                    user_id=str(row[1] or ""),
                    user_ids={str(k): str(v) for k, v in user_ids.items()} if isinstance(user_ids, dict) else {},
                    agent_id=str(row[2] or ""),
                    platform=str(row[3] or ""),
                    group_id=str(row[4]) if row[4] else None,
                    is_group=bool(row[5]),
                    created_at=int(row[6] or 0),
                    last_active=int(row[7] or 0),
                    state=str(row[8] or "active"),
                    platform_session_id=str(row[9] or ""),
                )
            self._sessions[session_key] = session
            self._by_id[session.session_id] = session_key
            logger.debug("会话从持久化恢复", session_id=session.session_id, key=session_key)
            return session
        except Exception as exc:  # noqa: BLE001
            logger.warning("SessionManager 持久化读取失败, 按新会话处理", error=str(exc))
            return None

    async def _persist(self, session: Session, session_key: str) -> None:
        """写穿会话 (best-effort: 持久化失败只记日志, 不阻塞消息流)。"""
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO sessions "
                    "(session_id, session_key, user_id, agent_id, platform, group_id, "
                    "is_group, created_at, last_active, state, platform_session_id, user_ids) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session.session_id,
                        session_key,
                        session.user_id,
                        session.agent_id,
                        session.platform,
                        session.group_id,
                        int(session.is_group),
                        session.created_at,
                        session.last_active,
                        session.state,
                        # Fix-79: platform_session_id/user_ids 一并写穿 (muted_until
                        # 是 monotonic 运行时值, 重启无意义, 不持久化)
                        session.platform_session_id,
                        json.dumps(session.user_ids or {}, ensure_ascii=False),
                    ),
                )
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("SessionManager 持久化写入失败, 已忽略", error=str(exc))

    async def _delete_from_db(self, session_id: str) -> None:
        """删除库行 (close/gc 时调用, best-effort)。"""
        if self._db_path is None:
            return
        try:
            await self._ensure_schema()
            import aiosqlite

            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("SessionManager 持久化删除失败, 已忽略", error=str(exc))
