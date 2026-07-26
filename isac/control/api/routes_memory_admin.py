"""N2 Memory 治理 Control API 路由 (MEMORY_DESIGN.md §7)。

N2 已落地: freeze/protect/correct/delete/restore/export 真实委托 MemoryGovernor
(操作 episodes 治理列 + memory_audit + memory_revisions 表)。Bearer Token 认证;
无 metadata_store 时整个路由不挂载 (404, 与 routes_memory 一致)。
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
        ok = await governor.freeze(item_id)
        return {"ok": ok, "detail": "frozen" if ok else "item not found or already frozen"}

    @router.post("/memory/{agent_id}/items/{item_id}/protect")
    async def protect(agent_id: str, item_id: str) -> dict:
        ok = await governor.protect(item_id)
        return {"ok": ok, "detail": "protected" if ok else "item not found or already protected"}

    @router.patch("/memory/{agent_id}/items/{item_id}")
    async def correct(agent_id: str, item_id: str, new_content: str = "") -> dict:
        ok = await governor.correct(item_id, new_content)
        return {"ok": ok, "detail": "corrected with revision history" if ok else "item not found"}

    @router.delete("/memory/{agent_id}/items/{item_id}")
    async def delete(agent_id: str, item_id: str) -> dict:
        ok = await governor.delete(item_id)
        return {
            "ok": ok,
            "detail": "soft deleted" if ok else "item not found or protected (refused)",
        }

    @router.post("/memory/{agent_id}/items/{item_id}/restore")
    async def restore(agent_id: str, item_id: str) -> dict:
        ok = await governor.restore(item_id)
        return {"ok": ok, "detail": "restored" if ok else "item not found"}

    @router.get("/memory/{agent_id}/items")
    async def list_items(agent_id: str) -> dict:
        items = await governor.export(agent_id)
        return {
            "ok": True,
            "count": len(items),
            "items": [
                {
                    "id": it.id,
                    "content": it.content,
                    "type": it.memory_type.value,
                    "frozen": it.metadata.get("frozen", 0),
                    "protected": it.metadata.get("protected", 0),
                    "deleted": it.metadata.get("deleted", 0),
                }
                for it in items
            ],
        }

    return router
