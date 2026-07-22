"""G2 MCP Server 测试 - JSON-RPC 2.0 + Token 认证。"""

from __future__ import annotations

import json

import pytest

from isac.control.mcp_server import ISACMCPServer, MCPError
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


@pytest.fixture
def mcp_server(tmp_path):
    services = {
        "global_config": {},
        "provider_manager": _StubProviderManager(),
        "memory_factory": lambda namespace: _StubMemory(namespace),
    }
    agent_manager = AgentManager(services)
    bus = InterAgentBus()
    router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
    server = ISACMCPServer(
        services=services,
        api_token="mcp-secret",
        agent_manager=agent_manager,
        router=router,
        bus=bus,
    )
    return server


class TestInitializeAndToolsList:
    @pytest.mark.asyncio
    async def test_initialize_returns_protocol_info(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        result = response["result"]
        assert result["protocolVersion"] == ISACMCPServer.PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == "isac-mcp"

    @pytest.mark.asyncio
    async def test_tools_list_returns_all_specs(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        )
        tools = response["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "agent_create" in names
        assert "link_create" in names
        assert "route_set_default" in names

    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {"jsonrpc": "2.0", "id": 3, "method": "nonexistent", "params": {}}
        )
        assert "error" in response
        assert response["error"]["code"] == -32601


class TestTokenAuth:
    """tools/call 需要 token 认证; protocol-level 方法 (initialize/tools/list) 不需要。"""

    @pytest.mark.asyncio
    async def test_tools_call_without_token_returns_unauthorized(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "agent_create", "arguments": {}},
            }
        )
        assert "error" in response
        assert response["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tools_call_with_wrong_token_returns_unauthorized(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer wrong"},
                    "name": "agent_create",
                    "arguments": {},
                },
            }
        )
        assert response["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_tools_call_with_correct_token_passes(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer mcp-secret"},
                    "name": "link_create",
                    "arguments": {"from_agent": "x", "to_agent": "y"},
                },
            }
        )
        assert "result" in response


class TestToolCall:
    @pytest.mark.asyncio
    async def test_agent_create_via_mcp(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer mcp-secret"},
                    "name": "agent_create",
                    "arguments": {"agent_id": "mcp_agent", "display_name": "MCP Agent"},
                },
            }
        )
        result = json.loads(response["result"]["content"][0]["text"])
        assert result["agent_id"] == "mcp_agent"
        assert result["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_link_create_via_mcp(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer mcp-secret"},
                    "name": "link_create",
                    "arguments": {"from_agent": "a", "to_agent": "b", "direction": "both"},
                },
            }
        )
        result = json.loads(response["result"]["content"][0]["text"])
        assert result["status"] == "added"
        # 验证 Link 真的添加到 bus
        links = mcp_server._bus.list_links()  # type: ignore[union-attr]
        assert any(link.from_agent == "a" and link.to_agent == "b" for link in links)

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, mcp_server) -> None:
        response = await mcp_server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer mcp-secret"},
                    "name": "nonexistent_tool",
                    "arguments": {},
                },
            }
        )
        assert "error" in response
        assert response["error"]["code"] == -32602


class TestNotification:
    @pytest.mark.asyncio
    async def test_notification_returns_none(self, mcp_server) -> None:
        # id 为 None 表示 notification, 不应返回 response
        response = await mcp_server._handle_request(
            {"jsonrpc": "2.0", "method": "shutdown", "params": {}}
        )
        assert response is None


class TestMCPError:
    def test_mcp_error_carries_code_and_message(self) -> None:
        err = MCPError(-32601, "not found")
        assert err.code == -32601
        assert err.message == "not found"
        assert str(err) == "not found"
