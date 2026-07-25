"""J3 Providers / Artifacts Control API 路由 (CONTROL_PLANE_SPEC.md)。

端点:
- GET    /providers                列出已注册 Provider (从 ProviderManager._multimodal_providers)
- GET    /providers/models        列出 ModelCatalog 全部 ModelDescriptor
- POST   /providers/{id}/test      测试 Provider 健康性 (返回 ok/error; TODO 真实 ping)
- GET    /artifacts                列出 ArtifactStore 全部制品元数据
- GET    /artifacts/{id}           查询单个制品元数据
- DELETE /artifacts/{id}           删除制品 (文件 + DB 行)

Bearer Token 认证; 无 artifact_store 时 /artifacts/* 不挂载 (404)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.artifacts.store import ArtifactStore
    from isac.provider.catalog import ModelCatalog
    from isac.provider.manager import ProviderManager


def build_router(
    provider_manager: ProviderManager,
    model_catalog: ModelCatalog,
    artifact_store: ArtifactStore | None,
    auth_dependency: Any = None,
    scope_dependency: Any = None,
) -> Any:
    """构造 Providers / Artifacts Control API 路由。"""
    from fastapi import APIRouter, Depends

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["providers"], dependencies=deps)

    _register_provider_routes(router, provider_manager, model_catalog, scope_dependency)
    if artifact_store is not None:
        _register_artifact_routes(router, artifact_store, scope_dependency)
    return router


def _register_provider_routes(
    router: Any, provider_manager: ProviderManager, model_catalog: ModelCatalog, scope_dependency: Any = None,
) -> None:
    """注册 /providers/* 端点。"""
    from fastapi import Depends, HTTPException

    read_deps = [Depends(scope_dependency("provider:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("provider:write"))] if scope_dependency else []

    @router.get("/providers", dependencies=read_deps)
    async def list_providers() -> dict:
        providers = []
        for (pid, mid), _provider in provider_manager._multimodal_providers.items():
            providers.append({"provider_id": pid, "model_id": mid})
        return {"providers": providers}

    @router.get("/providers/models", dependencies=read_deps)
    async def list_models() -> dict:
        models = [_descriptor_to_dict(d) for d in model_catalog.list_all()]
        return {"models": models}

    @router.post("/providers/{provider_id}/test", dependencies=write_deps)
    async def test_provider(provider_id: str, model_id: str = "") -> dict:
        found = any(
            pid == provider_id and (not model_id or mid == model_id)
            for (pid, mid) in provider_manager._multimodal_providers.keys()
        )
        if not found:
            raise HTTPException(
                status_code=404,
                detail={"code": "PROVIDER_NOT_FOUND", "message": f"{provider_id}/{model_id}"},
            )
        return {"provider_id": provider_id, "status": "ok"}


def _register_artifact_routes(router: Any, artifact_store: ArtifactStore, scope_dependency: Any = None) -> None:
    """注册 /artifacts/* 端点 (仅 artifact_store 非 None 时调用)。"""
    from fastapi import Depends, HTTPException

    read_deps = [Depends(scope_dependency("artifact:read"))] if scope_dependency else []
    delete_deps = [Depends(scope_dependency("artifact:delete"))] if scope_dependency else []

    @router.get("/artifacts", dependencies=read_deps)
    async def list_artifacts() -> dict:
        artifacts = await _list_artifacts_from_store(artifact_store)
        return {"artifacts": artifacts}

    @router.get("/artifacts/{artifact_id}", dependencies=read_deps)
    async def get_artifact(artifact_id: str) -> dict:
        meta = await _get_artifact_meta(artifact_store, artifact_id)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": artifact_id},
            )
        return meta

    @router.delete("/artifacts/{artifact_id}", dependencies=delete_deps)
    async def delete_artifact(artifact_id: str) -> dict:
        meta = await _get_artifact_meta(artifact_store, artifact_id)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "ARTIFACT_NOT_FOUND", "message": artifact_id},
            )
        await _delete_artifact(artifact_store, artifact_id)
        return {"artifact_id": artifact_id, "status": "deleted"}


def _descriptor_to_dict(d: Any) -> dict:
    """ModelDescriptor → dict。"""
    return {
        "provider_id": d.provider_id,
        "model_id": d.model_id,
        "operations": sorted(d.operations),
        "modalities_in": sorted(d.modalities_in),
        "modalities_out": sorted(d.modalities_out),
        "cost_tier": d.cost_tier,
        "latency_tier": d.latency_tier,
    }


async def _list_artifacts_from_store(store: Any) -> list[dict]:
    """从 ArtifactStore 元数据 DB 列出全部制品 (无 file 内容, 只元数据)。"""
    import aiosqlite

    await store._ensure_schema()
    artifacts: list[dict] = []
    async with aiosqlite.connect(store._db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT artifact_id, kind, mime_type, size_bytes, duration_seconds, "
            "created_at, expires_at, uri FROM artifacts ORDER BY created_at DESC LIMIT 200"
        )
        rows = await cursor.fetchall()
        for row in rows:
            artifacts.append(dict(row))
    return artifacts


async def _get_artifact_meta(store: Any, artifact_id: str) -> dict | None:
    """查询单个制品元数据; 不存在返回 None。"""
    import aiosqlite

    await store._ensure_schema()
    async with aiosqlite.connect(store._db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT artifact_id, kind, mime_type, size_bytes, duration_seconds, "
            "created_at, expires_at, uri FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row is not None else None


async def _delete_artifact(store: Any, artifact_id: str) -> None:
    """删除制品 (文件 + DB 行)。"""
    import asyncio

    import aiosqlite

    await store._ensure_schema()
    async with aiosqlite.connect(store._db_path) as db:
        await db.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
        await db.commit()
    file_path = store._file_path(artifact_id)
    await asyncio.to_thread(_delete_file_sync, file_path)


def _delete_file_sync(file_path: Any) -> None:
    """同步删文件 + 清理空分桶目录。"""
    try:
        file_path.unlink()
    except FileNotFoundError:
        pass
    try:
        file_path.parent.rmdir()
    except OSError:
        pass
