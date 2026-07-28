"""J3 Memory Control API 路由 (CONTROL_PLANE_SPEC.md)。

端点:
- GET /memory/{agent_id}/episodes   列出该 Agent 的记忆 episode (按 agent_id 命名空间)
- GET /memory/{agent_id}/profiles   列出人物画像
- GET /memory/{agent_id}/jargon     列出术语

Bearer Token 认证; 无 metadata_store 时整个路由不挂载 (404)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.memory.storage.metadata import MetadataStore


def build_router(
    metadata_store: MetadataStore | None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
) -> Any:
    """构造 Memory Control API 路由。无 metadata_store 时返回 None (不挂载)。"""
    if metadata_store is None:
        return None
    from fastapi import APIRouter, Depends, Query

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["memory"], dependencies=deps)
    # CR3-Fix: 这些端点会返回会话内容 / 人物画像 (PII), 治理路由 routes_memory_admin
    # 已按 memory:read 收窄, 但读路由此前完全没接 scope_dependency —— control.tokens[]
    # 生效时, 任意合法 token (哪怕只有 usage:read) 都能读所有 Agent 的记忆与画像。
    # 补齐 memory:read 门禁; scope_dependency 为 None (未配 tokens[]) 时 read_deps 为空,
    # 只受 auth_dependency 约束, 行为与之前完全一致 (向后兼容)。
    read_deps = [Depends(scope_dependency("memory:read"))] if scope_dependency else []

    @router.get("/memory/{agent_id}/episodes", dependencies=read_deps)
    async def list_episodes(agent_id: str, limit: int = Query(default=100, ge=1, le=500)) -> dict:
        episodes = await _query_episodes_by_agent(metadata_store, agent_id, limit)
        return {"episodes": episodes}

    @router.get("/memory/{agent_id}/profiles", dependencies=read_deps)
    async def list_profiles(agent_id: str) -> dict:
        profiles = await _query_profiles_by_agent(metadata_store, agent_id)
        return {"profiles": profiles}

    @router.get("/memory/{agent_id}/jargon", dependencies=read_deps)
    async def list_jargon(agent_id: str) -> dict:
        jargon = await _query_jargon_by_agent(metadata_store, agent_id)
        return {"jargon": jargon}

    return router


async def _query_episodes_by_agent(store: Any, agent_id: str, limit: int) -> list[dict]:
    """从 MetadataStore 查询某 agent_id 的 episodes。

    CR3-Fix: 排除软删除行 (deleted=1) —— 检索链路 (FTS/BM25/向量) 与预热都过滤墓碑,
    读端点若把已删除内容原文吐出, 治理 delete 的"已删除"语义就被绕过 (合规导出
    走 MemoryGovernor.export, 那才是有意包含软删条目的通道)。
    """
    import aiosqlite

    rows: list[dict] = []
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, session_id, user_id, content, summary, importance, created_at "
            "FROM episodes WHERE agent_id = ? AND deleted = 0 ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        for row in await cursor.fetchall():
            rows.append(dict(row))
    return rows


async def _query_profiles_by_agent(store: Any, agent_id: str) -> list[dict]:
    """从 MetadataStore 查询某 agent_id 的人物画像。"""
    import aiosqlite

    rows: list[dict] = []
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT person_id, name, profile_text, relationship_depth, interaction_count, "
            "first_seen, last_seen FROM person_profiles WHERE agent_id = ? "
            "ORDER BY last_seen DESC LIMIT 200",
            (agent_id,),
        )
        for row in await cursor.fetchall():
            rows.append(dict(row))
    return rows


async def _query_jargon_by_agent(store: Any, agent_id: str) -> list[dict]:
    """从 MetadataStore 查询某 agent_id 的术语。"""
    import aiosqlite

    rows: list[dict] = []
    async with aiosqlite.connect(store.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT word, meaning, context, usage_count, created_at FROM jargon_entries "
            "WHERE agent_id = ? ORDER BY usage_count DESC, word ASC LIMIT 200",
            (agent_id,),
        )
        for row in await cursor.fetchall():
            rows.append(dict(row))
    return rows
