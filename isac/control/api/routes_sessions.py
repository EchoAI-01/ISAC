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
    scope_dependency: Any = None,
) -> Any:
    """构造 Sessions Control API 路由。"""
    from fastapi import APIRouter, Depends, HTTPException, Query

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["sessions"], dependencies=deps)
    # CR3-Fix: /sessions/{id}/messages 直接返回会话消息文本 (与 memory episodes 同等
    # 敏感), 但此前没接 scope_dependency —— control.tokens[] 生效时任意合法 token 都能
    # 读所有会话与消息历史。补齐 memory:read 门禁 (会话内容属记忆读权限范畴);
    # scope_dependency 为 None 时 read_deps 为空, 行为与之前一致 (向后兼容)。
    read_deps = [Depends(scope_dependency("memory:read"))] if scope_dependency else []

    @router.get("/sessions", dependencies=read_deps)
    async def list_sessions(agent_id: str | None = None) -> dict:
        sessions = await session_manager.list_sessions(agent_id=agent_id)
        return {"sessions": [_session_to_dict(s) for s in sessions]}

    @router.get("/sessions/{session_id}", dependencies=read_deps)
    async def get_session(session_id: str) -> dict:
        session = await session_manager.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "SESSION_NOT_FOUND", "message": session_id},
            )
        return _session_to_dict(session)

    @router.get("/sessions/{session_id}/messages", dependencies=read_deps)
    async def get_session_messages(
        session_id: str, limit: int = Query(default=100, ge=1, le=500)
    ) -> dict:
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
    """从 MetadataStore 查询某 session_id 的 episodes (租户作用域)。

    Fix-94: 此前直连 ``store.db_path`` 裸 SQL 查 episodes, 绕过 U4 已建立的租户
    谓词 —— tenancy.enabled 且多租户共享同一 DB 时, 任一租户的 memory:read token
    可遍历 session_id 读到**其他租户**的会话消息原文 (U4 修掉了 episodes/profiles/
    jargon 三个读端点, 独漏此处)。改与 routes_memory ``_query_episodes_by_agent``
    同构: 经 ``store._tenant_db.scoped()`` (投影含 organization_id/tenant_id 列,
    enforce 子查询包裹) + ``tdb.connect()``; 隔离未生效时 scoped() 原样直通, 行为不变。
    CR3-Fix 保留: 排除软删除行 (deleted=1), 与检索链路/routes_memory 墓碑过滤一致。
    """
    import aiosqlite

    tdb = getattr(store, "_tenant_db", None)
    if tdb is None:
        return []
    query, params = tdb.scoped(
        "SELECT id, content, session_id, created_at, organization_id, tenant_id "
        "FROM episodes WHERE session_id = ? AND deleted = 0 "
        "ORDER BY created_at DESC LIMIT ?",
        [session_id, limit],
    )
    rows: list[dict] = []
    async with tdb.connect() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        for row in await cursor.fetchall():
            rows.append(dict(row))
    return rows
