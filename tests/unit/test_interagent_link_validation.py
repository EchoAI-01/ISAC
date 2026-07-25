"""Fix-16: InterAgentLink.from_agent/to_agent 格式校验。

CODE_REVIEW_REPORT.md 发现的存储型 XSS 链路: routes_routing.py::add_link 之前
把请求体里的 from_agent/to_agent 原样构造 InterAgentLink, 未经任何格式校验就
经 bus.add_link() 写入 data/links.jsonc, 并在审计日志 target 字段
(f"{link.from_agent}->{link.to_agent}") 里原样保留。WebUI 的
Dashboard/审计日志表格用 innerHTML 字符串拼接渲染这些字段 (app.js), 一个含
<script> 的 from_agent 值可以在管理员打开 Dashboard 时执行、窃取
sessionStorage 里的 Bearer Token。

修复分两层:
1. InterAgentLink.__post_init__ 复用 AgentConfig 已验证过的 AGENT_ID_PATTERN
   (isac/runtime/config.py), 在构造期直接拒绝格式非法的 from_agent/to_agent
   (连审计日志字段本身都不会是恶意内容) —— 本文件测试这一层。
2. app.js 审计日志渲染改用 textContent 逐格赋值 (不再用 innerHTML 拼接) ——
   Playwright/Chromium 二进制在本环境未下载 (playwright install 缺失, 是既有
   的环境缺口, 不在本次修复范围), 这一层改动通过静态源码断言覆盖, 见
   tests/unit/test_webui.py 里新增的用例。
"""

from __future__ import annotations

import pytest

from isac.runtime.bus import InterAgentLink


class TestInterAgentLinkValidation:
    def test_valid_agent_ids_construct_successfully(self) -> None:
        link = InterAgentLink(from_agent="agent-a", to_agent="agent_b")
        assert link.from_agent == "agent-a"
        assert link.to_agent == "agent_b"

    def test_script_tag_in_from_agent_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="from_agent"):
            InterAgentLink(from_agent="<script>alert(1)</script>", to_agent="b")

    def test_script_tag_in_to_agent_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="to_agent"):
            InterAgentLink(from_agent="a", to_agent="<img src=x onerror=alert(1)>")

    def test_empty_from_agent_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="from_agent"):
            InterAgentLink(from_agent="", to_agent="b")

    def test_overlong_agent_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="to_agent"):
            InterAgentLink(from_agent="a", to_agent="x" * 65)

    def test_slash_in_agent_id_is_rejected(self) -> None:
        """"/" 不在 AGENT_ID_PATTERN 白名单内, 顺带防住任何路径穿越式误用。"""
        with pytest.raises(ValueError, match="from_agent"):
            InterAgentLink(from_agent="../escaped", to_agent="b")


class TestAddLinkEndpointRejectsMalformedAgentIds:
    """走真实 HTTP 路径: POST /links 收到恶意 from_agent/to_agent 时必须 400,
    而不是 500 (未处理的 ValueError) 或 200 (静默写入恶意内容)。"""

    def _make_client(self, tmp_path):
        from fastapi.testclient import TestClient

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
            config={
                "api_token": "secret-token-123",
                "links_path": str(tmp_path / "links.jsonc"),
            },
        )
        return TestClient(app), bus

    def test_script_tag_from_agent_returns_400_not_persisted(self, tmp_path) -> None:
        client, bus = self._make_client(tmp_path)
        response = client.post(
            "/api/v1/links",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"from_agent": "<script>alert(1)</script>", "to_agent": "b"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "INVALID_CONFIG"
        assert bus.list_links() == []
        assert not (tmp_path / "links.jsonc").exists()

    def test_valid_agent_ids_still_succeed(self, tmp_path) -> None:
        client, bus = self._make_client(tmp_path)
        response = client.post(
            "/api/v1/links",
            headers={"Authorization": "Bearer secret-token-123"},
            json={"from_agent": "a", "to_agent": "b"},
        )
        assert response.status_code == 200
        assert len(bus.list_links()) == 1
