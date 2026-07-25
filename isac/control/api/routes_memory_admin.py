"""N2 Memory 治理 Control API 路由 (MEMORY_DESIGN.md §7)。

[框架已搭建 / scaffolding] freeze/protect/correct/delete/restore 写端点挂接点就位,
委托 MemoryGovernor;骨架阶段 governor 为 no-op (返回 ok=false), 真实治理留待 N2。
Bearer Token 认证; 无 metadata_store 时整个路由不挂载 (404, 与 routes_memory 一致)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.memory.storage.metadata import MetadataStore


def build_router(
    metadata_store: MetadataStore | None,
    auth_dependency: Any = None,
) -> Any:
    """构造 Memory 治理路由。无 metadata_store 时返回 None (不挂载)。"""
    if metadata_store is None:
        return None
    from fastapi import APIRouter, Depends

    from isac.memory.model import MemoryGovernor

    governor = MemoryGovernor(metadata_store)
    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["memory-admin"], dependencies=deps)

    @router.post("/memory/{agent_id}/items/{item_id}/freeze")
    async def freeze(agent_id: str, item_id: str) -> dict:
        return {"ok": await governor.freeze(item_id), "detail": "N2 记忆治理待落地"}

    @router.post("/memory/{agent_id}/items/{item_id}/protect")
    async def protect(agent_id: str, item_id: str) -> dict:
        return {"ok": await governor.protect(item_id), "detail": "N2 记忆治理待落地"}

    @router.patch("/memory/{agent_id}/items/{item_id}")
    async def correct(agent_id: str, item_id: str, new_content: str = "") -> dict:
        return {"ok": await governor.correct(item_id, new_content), "detail": "N2 记忆治理待落地"}

    @router.delete("/memory/{agent_id}/items/{item_id}")
    async def delete(agent_id: str, item_id: str) -> dict:
        return {"ok": await governor.delete(item_id), "detail": "N2 记忆治理待落地"}

    @router.post("/memory/{agent_id}/items/{item_id}/restore")
    async def restore(agent_id: str, item_id: str) -> dict:
        return {"ok": await governor.restore(item_id), "detail": "N2 记忆治理待落地"}

    return router
