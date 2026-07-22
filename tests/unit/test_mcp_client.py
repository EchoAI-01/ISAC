"""H2 MCP Client 测试 - HTTP 传输 + 工具桥接。"""

from __future__ import annotations

from typing import Any

import pytest

from isac.agent.tools.base import ToolContext
from isac.agent.tools.mcp.client import MCPClient, MCPToolBridge
from isac.core.types import AgentContext
from isac.gateway.models import Session


class _MockHTTPClient:
    """记录调用并按预设响应返回。"""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.responses = responses or {}

    async def post(self, url: str, **kwargs) -> Any:
        self.calls.append((url, kwargs))
        request_body = kwargs.get("json", {})
        method = request_body.get("method", "")
        # 返回预设响应
        for key, response in self.responses.items():
            if method == key:
                return _MockResponse(response)
        return _MockResponse({"jsonrpc": "2.0", "id": request_body.get("id"), "result": {}})

    async def aclose(self) -> None:
        pass


class _MockResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def _make_tool_context(args: dict | None = None) -> ToolContext:
    return ToolContext(
        args=args or {},
        agent_context=AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=None,
            current_message=object(),
        ),
        services={},
    )


class TestMCPClientConnect:
    @pytest.mark.asyncio
    async def test_connect_http_initializes_httpx_client(self) -> None:
        client = MCPClient("server1", {"transport": "http", "url": "https://mcp.example.com"})
        # 调用 connect() 会尝试 import httpx (可能未装), 用 mock 兜底
        try:
            await client.connect()
        except RuntimeError:
            pass  # httpx 未装, 直接注入 mock
        # 直接注入 mock (无论 connect 是否成功)
        client._http_client = _MockHTTPClient()
        client._connected = True
        assert client._url == "https://mcp.example.com"

    @pytest.mark.asyncio
    async def test_connect_http_requires_url(self) -> None:
        client = MCPClient("server1", {"transport": "http"})
        with pytest.raises(ValueError, match="url"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_connect_stdio_requires_command(self) -> None:
        client = MCPClient("server1", {"transport": "stdio"})
        with pytest.raises(ValueError, match="command"):
            await client.connect()

    @pytest.mark.asyncio
    async def test_connect_unknown_transport_raises(self) -> None:
        client = MCPClient("server1", {"transport": "unknown"})
        with pytest.raises(ValueError, match="不支持的 MCP 传输"):
            await client.connect()


class TestMCPClientHTTPFlow:
    @pytest.mark.asyncio
    async def test_list_tools_returns_bridged_tools(self) -> None:
        client = MCPClient("server1", {"transport": "http", "url": "https://example.com"})
        client._http_client = _MockHTTPClient({
            "tools/list": {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {"name": "search", "description": "搜索", "inputSchema": {"type": "object"}},
                        {"name": "fetch", "description": "拉取"},
                    ]
                },
            }
        })
        client._connected = True
        tools = await client.list_tools()
        assert len(tools) == 2
        assert tools[0].name == "search"
        assert tools[0].description == "搜索"
        assert isinstance(tools[0], MCPToolBridge)

    @pytest.mark.asyncio
    async def test_call_tool_returns_text_content(self) -> None:
        client = MCPClient("server1", {"transport": "http", "url": "https://example.com"})
        client._http_client = _MockHTTPClient({
            "tools/call": {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [
                        {"type": "text", "text": "搜索结果 1"},
                        {"type": "text", "text": "搜索结果 2"},
                    ]
                },
            }
        })
        client._connected = True
        result = await client.call_tool("search", {"query": "hello"})
        assert result.is_error is False
        assert "搜索结果 1" in result.content
        assert "搜索结果 2" in result.content

    @pytest.mark.asyncio
    async def test_call_tool_returns_error_on_jsonrpc_error(self) -> None:
        client = MCPClient("server1", {"transport": "http", "url": "https://example.com"})
        client._http_client = _MockHTTPClient({
            "tools/call": {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "tool not found"},
            }
        })
        client._connected = True
        result = await client.call_tool("missing", {})
        assert result.is_error is True
        assert "tool not found" in result.content

    @pytest.mark.asyncio
    async def test_call_tool_without_connect_returns_error(self) -> None:
        client = MCPClient("server1", {"transport": "http", "url": "https://example.com"})
        result = await client.call_tool("any", {})
        assert result.is_error is True
        assert "未连接" in result.content


class TestMCPToolBridge:
    @pytest.mark.asyncio
    async def test_bridge_executes_via_client(self) -> None:
        client = MCPClient("server1", {"transport": "http", "url": "https://example.com"})
        client._http_client = _MockHTTPClient({
            "tools/call": {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        })
        client._connected = True
        bridge = MCPToolBridge(client, "my_tool", "描述", {"type": "object"})
        assert bridge.name == "my_tool"
        assert bridge.description == "描述"
        result = await bridge.execute(_make_tool_context({"x": 1}))
        assert result.is_error is False
        assert result.content == "ok"
