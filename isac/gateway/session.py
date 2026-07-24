"""SessionManager: 会话查找/创建与持久化。

会话归属: Session 含 agent_id 字段 (SPECIFICATION.md 1.2)，
同一会话在不同 Agent 下是相互独立的 Session。

K7: 内存实现 + TTL 回收 + session_id 二级索引 (替代线性扫描)。
"""

from __future__ import annotations

from typing import Any

from isac.channel.model import ISACMessage
from isac.gateway.models import Session
from isac.utils.helpers import new_id, unix_now
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 小时无活动自动回收


class SessionManager:
    """会话管理器。

    K7: 加 session_id 二级索引 + TTL 回收, 长期运行不内存膨胀;
    get(session_id) 由 O(N) 降为 O(1)。
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._sessions: dict[str, Session] = {}  # session_key -> Session
        self._by_id: dict[str, str] = {}  # session_id -> session_key (二级索引)
        self._ttl_seconds = int(self.config.get("session_ttl_seconds", DEFAULT_TTL_SECONDS))

    def make_session_key(self, agent_id: str, platform: str, user_id: str, group_id: str | None) -> str:
        """生成会话键: agent + 平台 + (群 或 用户)。"""
        target = f"group:{group_id}" if group_id else f"user:{user_id}"
        return f"{agent_id}:{platform}:{target}"

    async def get_or_create(self, message: ISACMessage, agent_id: str) -> Session:
        """查找或创建会话。"""
        key = self.make_session_key(agent_id, message.platform, message.user_id, message.group_id)
        session = self._sessions.get(key)
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
        # 惰性回收: 每次 get_or_create 顺便清理过期 session
        self._gc_expired()
        return session

    async def get(self, session_id: str) -> Session | None:
        """按 session_id 查找 (O(1) 二级索引)。"""
        key = self._by_id.get(session_id)
        if key is None:
            return None
        return self._sessions.get(key)

    async def close(self, session_id: str) -> None:
        """关闭并移除会话。"""
        key = self._by_id.pop(session_id, None)
        if key is None:
            return
        session = self._sessions.pop(key, None)
        if session is not None:
            session.state = "closed"

    def _gc_expired(self) -> None:
        """惰性清理 TTL 过期会话 (K7: 防止长期运行内存膨胀)。"""
        if self._ttl_seconds <= 0:
            return
        cutoff = unix_now() - self._ttl_seconds
        expired_keys = [k for k, s in self._sessions.items() if s.last_active < cutoff]
        for key in expired_keys:
            session = self._sessions.pop(key, None)
            if session is not None:
                self._by_id.pop(session.session_id, None)
                logger.debug("回收过期会话", session_id=session.session_id, key=key)
