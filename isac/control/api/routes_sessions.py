"""J3 Sessions Control API 路由 (CONTROL_PLANE_SPEC.md)。

端点:
- GET /sessions                列出活跃会话 (可选 ?agent_id= 过滤)
- GET /sessions/{id}           查询单个会话详情
- GET /sessions/{id}/messages  列出会话消息历史 (从 MetadataStore.episodes)

Bearer Token 认证; 无 metadata_store 时 /messages 返回空列表。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.gateway.session import SessionManager
    from isac.memory.storage.metadata import MetadataStore


def build_router(
    session_manager: SessionManager,
    metadata_store: MetadataStore | None,
    auth_dependency: Any = None,
) -> Any:
    """构造 Sessions Control API 路由。"""
    from fastapi import APIRouter, Depends, HTTPException

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["sessions"], dependencies=deps)

    @router.get("/sessions")
    async def list_sessions(agent_id: str | None = None) -> dict:
        sessions = await session_manager.list_sessions(agent_id=agent_id)
        return {"sessions": [_session_to_dict(s) for s in sessions]}

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        session = await session_manager.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SESSION_NOT_FOUND", "message": session_id},
            )
        return _session_to_dict(session)

    @router.get("/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str, limit: int = 100) -> dict:
        """列出会话消息历史 (从 MetadataStore.episodes 按 session_id 查)。"""
        if metadata_store is None:
            return {"messages": []}
        # MetadataStore 按 session_id 查询 episodes (content 即消息文本)
        try:
            episodes = await _query_episodes_by_session(metadata_store, session_id, limit)
            messages = [
                {"memory_id": e["id"], "content": e["content"], "created_at": e["created_at"]}
                for e in episodes
            ]
            return {"messages": messages}
        except Exception:  # noqa: BLE001
            return {"messages": []}

    return router


def _session_to_dict(s: Any) -> dict:
    """Session → dict。"""
    return {
        "session_id": s.session_id,
        "agent_id": s.agent_id,
        "user_id": s.user_id,
        "platform": s.platform,
        "group_id": s.group_id,
        "is_group": s.is_group,
        "state": getattr(s, "state", "active"),
        "created_at": s.created_at,
        "last_active": getattr(s, "last_active", 0),
    }


async def _query_episodes_by_session(store: Any, session_id: str, limit: int) -> list[dict]:
    """从 MetadataStore 查询某 session_id 的 episodes。

    MetadataStore 当前没有按 session_id 直接查询的方法, 用 iter_episodes_by_namespace
    + 过滤 session_id 兜底 (性能不优, 但 J3 范围内可用; 后续可加专门索引)。
    """
    # MetadataStore 的 session_id 是 episode 行的 session_id 列; 直接 SQL 查
    import aiosqlite

    rows: list[dict] = []
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, content, session_id, created_at FROM episodes "
            "WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit),
        )
        for row in await cursor.fetchall():
            rows.append(dict(row))
    return rows
