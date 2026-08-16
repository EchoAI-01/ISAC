"""N5b 批次G: DELETE /agents/{id} 不存在时应返回 404 而非 500。

此前 destroy_agent 路由未捕获 agent_manager.destroy 内部抛出的 AgentNotFoundError
(经 _require), FastAPI 默认转 500 泄露内部异常; 现统一经 _require_agent 转 404。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _make_app(config: dict | None = None, agents_dir: str = "data/agents") -> Any:
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
    merged_config = dict(config if config is not None else {"api_token": "secret-token-123"})
    merged_config.setdefault("agents_dir", agents_dir)
    return create_control_app(
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
        config=merged_config,
    )


class TestDestroyAgentNotFound:
    def test_delete_missing_agent_returns_404_not_500(self) -> None:
        """DELETE 不存在 agent: AgentManager.destroy 内部 _require 抛
        AgentNotFoundError, 路由经 _require_agent 转 404 (此前未捕获 → 500)。"""
        client = TestClient(_make_app())
        resp = client.delete(
            "/api/v1/agents/nope-no-such-agent",
            headers={"Authorization": "Bearer secret-token-123"},
        )
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "AGENT_NOT_FOUND"
        assert "nope-no-such-agent" in detail["message"]

    def test_delete_missing_agent_keeps_memory_flag_accepted(self) -> None:
        """keep_memory 查询参数透传到 destroy; 不存在时仍 404 (参数校验先于存在性)。"""
        client = TestClient(_make_app())
        resp = client.delete(
            "/api/v1/agents/ghost?keep_memory=false",
            headers={"Authorization": "Bearer secret-token-123"},
        )
        assert resp.status_code == 404
