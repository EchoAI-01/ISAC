"""SessionManager: 会话查找/创建与持久化。

会话归属: Session 含 agent_id 字段 (SPECIFICATION.md 1.2)，
同一会话在不同 Agent 下是相互独立的 Session。
"""

from __future__ import annotations

from typing import Any

from isac.channel.model import ISACMessage
from isac.gateway.models import Session
from isac.utils.helpers import new_id, unix_now
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class SessionManager:
    """会话管理器。

    TODO(Day 6): SQLite 持久化 (data/sessions/)，启动时加载活跃会话。
    当前为内存实现，供框架联调使用。
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._sessions: dict[str, Session] = {}

    def make_session_key(self, agent_id: str, platform: str, user_id: str, group_id: str | None) -> str:
        """生成会话键: agent + 平台 + (群 或 用户)。"""
        target = f"group:{group_id}" if group_id else f"user:{user_id}"
        return f"{agent_id}:{platform}:{target}"

    async def get_or_create(self, message: ISACMessage, agent_id: str) -> Session:
        """查找或创建会话。

        TODO(Day 6): 持久化 + UserMapper 跨平台主用户识别。
        """
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
            logger.info("创建会话", session_id=session.session_id, key=key)
        session.last_active = unix_now()
        message.session_id = session.session_id
        return session

    async def get(self, session_id: str) -> Session | None:
        for session in self._sessions.values():
            if session.session_id == session_id:
                return session
        return None

    async def close(self, session_id: str) -> None:
        session = await self.get(session_id)
        if session:
            session.state = "closed"
