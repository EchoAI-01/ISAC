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

    @pytest.mark.asyncio
    async def test_channel_bind_and_unbind(self, mcp_server) -> None:
        """R2-④: channel_bind_agent + channel_unbind_agent 操作 RoutingRules.bindings。"""
        params = {"meta": {"authorization": "Bearer mcp-secret"}, "name": "", "arguments": {}}
        for tool in ("channel_bind_agent",):
            p = {**params, "name": tool, "arguments": {"platform": "webchat", "agent_id": "a1"}}
            resp = await mcp_server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": p})
            result = json.loads(resp["result"]["content"][0]["text"])
            assert result["status"] == "bound"
        rules = mcp_server._router.get_rules()
        assert any(b.platform == "webchat" and b.agent_id == "a1" for b in rules.bindings)
        # unbind
        p = {**params, "name": "channel_unbind_agent", "arguments": {"platform": "webchat", "agent_id": "a1"}}
        resp = await mcp_server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": p})
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "unbound"
        assert result["removed"] == 1

    @pytest.mark.asyncio
    async def test_plugin_set_enabled(self, mcp_server, tmp_path, monkeypatch) -> None:
        """R2-④: plugin_set_enabled 调整 plugins_allow/deny 并持久化。"""
        from isac.runtime.config import AgentConfig

        cfg = AgentConfig(agent_id="r2plug", display_name="R2")
        # chdir 到 tmp_path, 让工具内 save_agent_config 的 "data/agents" 相对路径落到临时目录
        monkeypatch.chdir(tmp_path)
        await mcp_server._agent_manager.create(cfg)
        resp = await mcp_server._handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"meta": {"authorization": "Bearer mcp-secret"}, "name": "plugin_set_enabled",
                       "arguments": {"agent_id": "r2plug", "plugins_allow": ["p1"], "plugins_deny": ["bad"]}},
        })
        result = json.loads(resp["result"]["content"][0]["text"])
        assert result["status"] == "updated"
        inst = await mcp_server._agent_manager.get("r2plug")
        assert inst.config.plugins_allow == ["p1"]
        assert inst.config.plugins_deny == ["bad"]
        # 持久化文件已写 (含自增 revision)
        assert (tmp_path / "data" / "agents" / "r2plug" / "config.jsonc").exists()


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


class TestScopeModel:
    """C2: parsed_tokens 启用时按工具→scope 映射校验, 防止被限制为
    usage:read 的 token 通过 MCP 调 agent_create/link_create/route_set_default
    等写操作 (权限提升)。"""

    def _make_server_with_tokens(
        self, tmp_path, tokens: list[dict]
    ) -> ISACMCPServer:
        from isac.control.auth import TokenScope
        services = {
            "global_config": {},
            "provider_manager": _StubProviderManager(),
            "memory_factory": lambda namespace: _StubMemory(namespace),
        }
        agent_manager = AgentManager(services)
        bus = InterAgentBus()
        router = MessageRouter(RoutingRules(), agents_provider=agent_manager.routing_infos)
        parsed = [
            TokenScope(token=t["token"], scopes=frozenset(t["scopes"]))
            for t in tokens
        ]
        return ISACMCPServer(
            services=services,
            api_token="",  # parsed_tokens 启用时 api_token 不再用于认证
            agent_manager=agent_manager,
            router=router,
            bus=bus,
            parsed_tokens=parsed,
        )

    @pytest.mark.asyncio
    async def test_usage_read_token_cannot_call_agent_create(self, tmp_path) -> None:
        """usage:read scope 调 agent_create (需要 agent:write) → 403 SCOPE_FORBIDDEN。"""
        server = self._make_server_with_tokens(
            tmp_path,
            tokens=[{"token": "limited", "scopes": ["usage:read"]}],
        )
        response = await server._handle_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer limited"},
                    "name": "agent_create",
                    "arguments": {"agent_id": "x", "display_name": "X"},
                },
            }
        )
        assert "error" in response
        assert response["error"]["code"] == -32003  # SCOPE_FORBIDDEN

    @pytest.mark.asyncio
    async def test_agent_write_token_can_call_agent_create(self, tmp_path) -> None:
        """agent:write scope 调 agent_create → 通过。"""
        server = self._make_server_with_tokens(
            tmp_path,
            tokens=[{"token": "writer", "scopes": ["agent:write"]}],
        )
        response = await server._handle_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer writer"},
                    "name": "agent_create",
                    "arguments": {"agent_id": "scope_agent", "display_name": "Scoped"},
                },
            }
        )
        assert "result" in response
        import json
        result = json.loads(response["result"]["content"][0]["text"])
        assert result["agent_id"] == "scope_agent"

    @pytest.mark.asyncio
    async def test_wildcard_scope_passes_all_tools(self, tmp_path) -> None:
        """scopes 含 "*" 通配符时所有工具都可调用。"""
        server = self._make_server_with_tokens(
            tmp_path,
            tokens=[{"token": "admin", "scopes": ["*"]}],
        )
        response = await server._handle_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer admin"},
                    "name": "link_create",
                    "arguments": {"from_agent": "a", "to_agent": "b"},
                },
            }
        )
        assert "result" in response

    @pytest.mark.asyncio
    async def test_unknown_token_rejected(self, tmp_path) -> None:
        """parsed_tokens 启用时, 不在 tokens[] 里的 token → 401。"""
        server = self._make_server_with_tokens(
            tmp_path,
            tokens=[{"token": "known", "scopes": ["agent:write"]}],
        )
        response = await server._handle_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer unknown-token"},
                    "name": "agent_create",
                    "arguments": {},
                },
            }
        )
        assert response["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_usage_read_token_cannot_call_link_create(self, tmp_path) -> None:
        """link_create 需要 link:write, usage:read 不够 → 403。"""
        server = self._make_server_with_tokens(
            tmp_path,
            tokens=[{"token": "limited", "scopes": ["usage:read"]}],
        )
        response = await server._handle_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer limited"},
                    "name": "link_create",
                    "arguments": {"from_agent": "a", "to_agent": "b"},
                },
            }
        )
        assert response["error"]["code"] == -32003

    @pytest.mark.asyncio
    async def test_routing_write_scope_for_route_set_default(self, tmp_path) -> None:
        """route_set_default 需要 routing:write。"""
        server = self._make_server_with_tokens(
            tmp_path,
            tokens=[{"token": "router", "scopes": ["routing:write"]}],
        )
        response = await server._handle_request(
            {
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "meta": {"authorization": "Bearer router"},
                    "name": "route_set_default",
                    "arguments": {"platform": "qq", "agent_id": "a1"},
                },
            }
        )
        assert "result" in response

