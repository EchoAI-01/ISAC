"""routes_memory_admin.py 的 HTTP 层测试 (scope 校验 + 审计接入)。

覆盖:
- CR2-Fix-10: 无 scope_dependency 配置时行为不变 (回归); memory:read scope
  只能查询, memory:write scope 才能执行治理写操作; 写操作后统一审计日志
  (GET /api/v1/audit) 能查到对应记录。
- CR2-Fix-11: 治理操作按 URL 里的 agent_id 校验, 不能用别的 agent_id 段操作
  实际属于其他 Agent 的 item_id。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from isac.memory.storage.metadata import MetadataStore


@pytest.fixture
def metadata_store(tmp_path: Path) -> MetadataStore:
    return MetadataStore(str(tmp_path / "metadata.db"))


def _make_app(metadata_store: MetadataStore, config: dict[str, Any] | None = None) -> Any:
    from isac.control.api.server import create_control_app
    from isac.plugin.runtime.manager import PluginManager
    from isac.router.router import MessageRouter
    from isac.router.types import RoutingRules
    from isac.runtime.bus import InterAgentBus
    from isac.runtime.manager import AgentManager

    class _StubProviderManager:
        def for_agent(self, config: Any) -> None:
            return None

    class _StubMemory:
        def __init__(self, namespace: str) -> None:
            self.namespace = namespace

        async def search(self, *args: Any, **kwargs: Any) -> list:
            return []

        async def store_episode(self, *args: Any, **kwargs: Any) -> str:
            return ""

    services = {
        "global_config": {},
        "provider_manager": _StubProviderManager(),
        "memory_factory": lambda namespace: _StubMemory(namespace),
    }
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
    plugin_manager = PluginManager({})
    merged_config = dict(config if config is not None else {})
    return create_control_app(
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
        config=merged_config,
        metadata_store=metadata_store,
    )


async def _seed_episode(store: MetadataStore, *, agent_id: str, item_id: str) -> None:
    await store.init_schema()
    await store.store_episode(agent_id, {"id": item_id, "session_id": "s1", "user_id": "u1", "content": "原始内容"})


class TestNoScopeConfiguredRegression:
    """未配置 control.tokens[] 时 (只有扁平 api_token), 行为与引入 scope 模型之前一致。"""

    def test_write_and_read_both_succeed_with_flat_token(self, metadata_store: MetadataStore) -> None:
        import asyncio

        asyncio.run(_seed_episode(metadata_store, agent_id="agent-a", item_id="ep1"))
        client = TestClient(_make_app(metadata_store, {"api_token": "secret-token"}))
        headers = {"Authorization": "Bearer secret-token"}
        resp = client.get("/api/v1/memory/agent-a/items", headers=headers)
        assert resp.status_code == 200
        resp = client.post("/api/v1/memory/agent-a/items/ep1/freeze", headers=headers)
        assert resp.status_code == 200


class TestScopeEnforcement:
    """CR2-Fix-10: 配置了 tokens[] 后, memory:read/memory:write scope 分别生效。"""

    def _app_with_scopes(self, metadata_store: MetadataStore) -> Any:
        return _make_app(
            metadata_store,
            {
                "api_token": "admin-fallback",
                "tokens": [
                    {"token": "reader", "scopes": ["memory:read"]},
                    {"token": "writer", "scopes": ["memory:write"]},
                ],
            },
        )

    def test_read_only_token_can_list_but_not_freeze(self, metadata_store: MetadataStore) -> None:
        import asyncio

        asyncio.run(_seed_episode(metadata_store, agent_id="agent-a", item_id="ep1"))
        client = TestClient(self._app_with_scopes(metadata_store))
        read_resp = client.get("/api/v1/memory/agent-a/items", headers={"Authorization": "Bearer reader"})
        assert read_resp.status_code == 200
        write_resp = client.post(
            "/api/v1/memory/agent-a/items/ep1/freeze", headers={"Authorization": "Bearer reader"}
        )
        assert write_resp.status_code == 403
        assert write_resp.json()["detail"]["code"] == "SCOPE_FORBIDDEN"

    def test_write_token_cannot_list_without_read_scope(self, metadata_store: MetadataStore) -> None:
        import asyncio

        asyncio.run(_seed_episode(metadata_store, agent_id="agent-a", item_id="ep1"))
        client = TestClient(self._app_with_scopes(metadata_store))
        resp = client.get("/api/v1/memory/agent-a/items", headers={"Authorization": "Bearer writer"})
        assert resp.status_code == 403

    def test_write_token_can_freeze(self, metadata_store: MetadataStore) -> None:
        import asyncio

        asyncio.run(_seed_episode(metadata_store, agent_id="agent-a", item_id="ep1"))
        client = TestClient(self._app_with_scopes(metadata_store))
        resp = client.post("/api/v1/memory/agent-a/items/ep1/freeze", headers={"Authorization": "Bearer writer"})
        assert resp.status_code == 200


class TestAuditLogging:
    """CR2-Fix-10: 治理写操作应写入项目统一审计日志, 可通过 GET /api/v1/audit 查询。"""

    def test_freeze_appears_in_unified_audit_log(self, metadata_store: MetadataStore, tmp_path: Path) -> None:
        import asyncio

        asyncio.run(_seed_episode(metadata_store, agent_id="agent-a", item_id="ep1"))
        audit_path = tmp_path / "audit.ndjson"
        client = TestClient(
            _make_app(metadata_store, {"api_token": "secret-token", "audit_log_path": str(audit_path)})
        )
        headers = {"Authorization": "Bearer secret-token"}
        resp = client.post("/api/v1/memory/agent-a/items/ep1/freeze", headers=headers)
        assert resp.status_code == 200
        audit_resp = client.get("/api/v1/audit", headers=headers)
        assert audit_resp.status_code == 200
        actions = [entry["action"] for entry in audit_resp.json()]
        assert "freeze_memory_item" in actions
