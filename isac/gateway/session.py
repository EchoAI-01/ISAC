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
    state TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_key ON sessions(session_key);
"""


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
        self._lock = asyncio.Lock()

    def make_session_key(self, agent_id: str, platform: str, user_id: str, group_id: str | None) -> str:
        """生成会话键: agent + 平台 + (群 或 用户)。"""
        target = f"group:{group_id}" if group_id else f"user:{user_id}"
        return f"{agent_id}:{platform}:{target}"

    async def get_or_create(self, message: ISACMessage, agent_id: str) -> Session:
        """查找或创建会话。

        R5: 缓存未命中时先查 SQLite (重启后恢复既有 session_id), 仍未命中才创建;
        每次 get_or_create 写穿 last_active (best-effort)。check-then-create 在
        ``_lock`` 内串行, 消除并发双创建。
        """
        key = self.make_session_key(agent_id, message.platform, message.user_id, message.group_id)
        async with self._lock:
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
        # 惰性回收: 每次 get_or_create 顺便清理过期 session (锁外, 不阻塞当前会话)
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
            await db.executescript(SCHEMA_SQL)
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
                    "created_at, last_active, state FROM sessions WHERE session_key = ?",
                    (session_key,),
                )
                row = await cursor.fetchone()
                if row is None:
                    return None
                session = Session(
                    session_id=str(row[0]),
                    user_id=str(row[1] or ""),
                    agent_id=str(row[2] or ""),
                    platform=str(row[3] or ""),
                    group_id=str(row[4]) if row[4] else None,
                    is_group=bool(row[5]),
                    created_at=int(row[6] or 0),
                    last_active=int(row[7] or 0),
                    state=str(row[8] or "active"),
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
                    "is_group, created_at, last_active, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
