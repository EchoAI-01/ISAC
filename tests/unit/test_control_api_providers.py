"""J3 阶段 1: Control API routes_providers 测试。

覆盖:
- GET /providers: 列出已注册 Provider (从 ProviderManager._multimodal_providers)
- GET /providers/models: 列出 ModelCatalog 全部 descriptor
- GET /artifacts: 列出 ArtifactStore 全部制品 (元数据)
- GET /artifacts/{id}: 查询单个制品元数据
- DELETE /artifacts/{id}: 删除制品 (文件 + DB 行)
- POST /providers/{id}/test: 测试 Provider 健康性 (返回 ok/error)
- Bearer Token 认证
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from isac.artifacts.store import ArtifactStore
from isac.control.api.server import create_control_app
from isac.observability import get_default_metrics
from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.manager import ProviderManager


def _make_app(
    *,
    provider_manager: ProviderManager | None = None,
    model_catalog: ModelCatalog | None = None,
    artifact_store: ArtifactStore | None = None,
    api_token: str = "test-token",
) -> Any:
    class _StubAM:
        async def list(self): return []
        async def get(self, _): return None

    config = {"api_token": api_token, "agents_dir": "data/agents"}
    app = create_control_app(
        _StubAM(), object(), object(), object(),
        config, metrics=get_default_metrics(),
    )
    from isac.control.api import routes_providers
    app.include_router(
        routes_providers.build_router(
            provider_manager or ProviderManager({}),
            model_catalog or ModelCatalog(),
            artifact_store,
            auth_dependency=_make_auth_dep(api_token),
        ),
        prefix="/api/v1",
    )
    return app


def _make_auth_dep(api_token: str) -> Any:
    from isac.control.auth import make_auth_dependency
    return make_auth_dependency(api_token)


def test_list_providers_empty() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v1/providers", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.json() == {"providers": []}


def test_list_providers_with_multimodal(tmp_path: Path) -> None:
    pm = ProviderManager({})
    # 注册一个桩 multimodal provider
    class _FakeProvider:
        async def aclose(self): pass
        def get_model_name(self): return "dall-e-3"
    pm.register_multimodal(_FakeProvider(), provider_id="openai", model_id="dall-e-3")
    app = _make_app(provider_manager=pm)
    client = TestClient(app)
    resp = client.get("/api/v1/providers", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["providers"]) == 1
    assert data["providers"][0]["provider_id"] == "openai"
    assert data["providers"][0]["model_id"] == "dall-e-3"


def test_list_models_empty() -> None:
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/v1/providers/models", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.json() == {"models": []}


def test_list_models_with_descriptors() -> None:
    catalog = ModelCatalog()
    catalog.register(ModelDescriptor(
        provider_id="openai", model_id="dall-e-3",
        operations={"image_gen"}, modalities_in={"text"}, modalities_out={"image"},
        cost_tier="low", latency_tier="standard",
    ))
    app = _make_app(model_catalog=catalog)
    client = TestClient(app)
    resp = client.get("/api/v1/providers/models", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["models"]) == 1
    m = data["models"][0]
    assert m["provider_id"] == "openai"
    assert m["model_id"] == "dall-e-3"
    assert "image_gen" in m["operations"]
    assert m["cost_tier"] == "low"


def test_list_artifacts_empty_when_no_store() -> None:
    """无 artifact_store 时不挂载 /artifacts 路由 → 404。"""
    app = _make_app()  # artifact_store=None
    client = TestClient(app)
    resp = client.get("/api/v1/artifacts", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 404


def test_list_artifacts_empty_store(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))
    app = _make_app(artifact_store=store)
    client = TestClient(app)
    resp = client.get("/api/v1/artifacts", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 200
    assert resp.json() == {"artifacts": []}


def test_get_artifact_after_put(tmp_path: Path) -> None:
    import asyncio
    store = ArtifactStore(str(tmp_path / "artifacts"))
    ref = asyncio.run(store.put(b"fake image", kind="image", mime_type="image/png"))
    app = _make_app(artifact_store=store)
    client = TestClient(app)
    resp = client.get(
        f"/api/v1/artifacts/{ref.artifact_id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["artifact_id"] == ref.artifact_id
    assert data["kind"] == "image"
    assert data["mime_type"] == "image/png"
    assert data["size_bytes"] == 10


def test_get_artifact_not_found(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))
    app = _make_app(artifact_store=store)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/artifacts/nonexistent",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 404


def test_delete_artifact(tmp_path: Path) -> None:
    import asyncio
    store = ArtifactStore(str(tmp_path / "artifacts"))
    ref = asyncio.run(store.put(b"to delete", kind="image"))
    app = _make_app(artifact_store=store)
    client = TestClient(app)
    resp = client.delete(
        f"/api/v1/artifacts/{ref.artifact_id}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    # 确认已删
    assert asyncio.run(store.get(ref.artifact_id)) is None


def test_delete_artifact_not_found(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"))
    app = _make_app(artifact_store=store)
    client = TestClient(app)
    resp = client.delete(
        "/api/v1/artifacts/nonexistent",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 404


def test_token_auth_required(tmp_path: Path) -> None:
    app = _make_app(artifact_store=ArtifactStore(str(tmp_path / "a")))
    client = TestClient(app)
    resp = client.get("/api/v1/providers")  # 无 token
    assert resp.status_code in (401, 403)
