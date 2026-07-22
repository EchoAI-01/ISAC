"""I1 WebUI 管理面板测试 - 静态托管 + API 集成。"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def webui_client(tmp_path: Path):
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi 未安装")
    from isac.control.api.server import create_control_app
    from isac.plugin.runtime.manager import PluginManager
    from isac.router.router import MessageRouter
    from isac.router.types import RoutingRules
    from isac.runtime.bus import InterAgentBus
    from isac.runtime.manager import AgentManager

    class _StubProviderManager:
        def for_agent(self, config):
            return None

    class _StubMemory:
        def __init__(self, namespace):
            self.namespace = namespace

        async def search(self, *args, **kwargs):
            return []

        async def store_episode(self, *args, **kwargs):
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

    app = create_control_app(
        agent_manager=agent_manager,
        router=router,
        bus=bus,
        plugin_manager=plugin_manager,
        config={"api_token": "ui-token"},
    )
    return TestClient(app)


class TestWebUIStatic:
    def test_index_html_returns_200(self, webui_client) -> None:
        response = webui_client.get("/ui/")
        assert response.status_code == 200
        assert "ISAC 管理面板" in response.text
        assert "<table" in response.text

    def test_app_js_returns_200(self, webui_client) -> None:
        response = webui_client.get("/ui/app.js")
        assert response.status_code == 200
        assert "apiCall" in response.text
        assert "Bearer" in response.text

    def test_index_contains_all_sections(self, webui_client) -> None:
        response = webui_client.get("/ui/")
        assert "Agent 管理" in response.text
        assert "路由规则" in response.text
        assert "互联 Link" in response.text
        assert "审计日志" in response.text

    def test_webui_does_not_require_token(self, webui_client) -> None:
        # WebUI 静态资源不需要 token (前端自己带 token 调 API)
        response = webui_client.get("/ui/")
        assert response.status_code == 200


class TestWebUIIntegrationWithAPI:
    def test_full_workflow_via_api(self, webui_client) -> None:
        # 通过 API 模拟 WebUI 的完整工作流
        headers = {"Authorization": "Bearer ui-token"}

        # 1. 创建 Agent
        r = webui_client.post("/api/v1/agents", headers=headers, json={"agent_id": "w1", "display_name": "W1"})
        assert r.status_code == 200

        # 2. 启动 Agent
        r = webui_client.post("/api/v1/agents/w1/start", headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] == "running"

        # 3. 列出 Agent (WebUI /agents endpoint)
        r = webui_client.get("/api/v1/agents", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1
        assert any(a["agent_id"] == "w1" for a in r.json())

        # 4. 添加 Link
        r = webui_client.post("/api/v1/links", headers=headers, json={
            "from_agent": "w1", "to_agent": "w2", "direction": "both"
        })
        assert r.status_code == 200

        # 5. 查询审计
        r = webui_client.get("/api/v1/audit?limit=10", headers=headers)
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 2  # create_agent + add_link
