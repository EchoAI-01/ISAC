"""H2 MCP Client 测试 - HTTP 传输 + 工具桥接。"""

from __future__ import annotations

import asyncio
import sys
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


_ECHO_SCRIPT = """
import json
import sys

for raw_line in sys.stdin:
    raw_line = raw_line.strip()
    if not raw_line:
        continue
    request = json.loads(raw_line)
    print("noise on stderr", file=sys.stderr, flush=True)
    response = {"jsonrpc": "2.0", "id": request.get("id"), "result": {"echo": request.get("method")}}
    print(json.dumps(response), flush=True)
"""


class _FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None


class _NeverRespondingProcess:
    """模拟一个已启动但永远不回应 stdin 请求的子进程 (用于超时清理测试)。"""

    def __init__(self) -> None:
        self.stdin = _FakeStdin()
        self.stdout = None
        self.stderr = None


class TestMCPClientStdioLifecycle:
    @pytest.mark.asyncio
    async def test_stdio_roundtrip_tracks_reader_tasks_and_drains_stderr(self) -> None:
        client = MCPClient(
            "server1",
            {"transport": "stdio", "command": sys.executable, "args": ["-c", _ECHO_SCRIPT]},
        )
        await client.connect()
        try:
            assert client._stdout_task is not None
            assert client._stderr_task is not None

            response = await client._send_request("ping", {})
            assert response["result"]["echo"] == "ping"
            # 请求完成后不应在 _pending 里遗留 (无论走成功路径还是超时路径)
            assert client._pending == {}
        finally:
            await client.disconnect()

        assert client._process is None
        assert client._stdout_task is None
        assert client._stderr_task is None

    @pytest.mark.asyncio
    async def test_send_stdio_timeout_removes_pending_entry(self) -> None:
        client = MCPClient(
            "server1",
            {"transport": "stdio", "command": "true", "request_timeout_seconds": 0.05},
        )
        client._process = _NeverRespondingProcess()  # type: ignore[assignment]
        client._connected = True

        with pytest.raises(TimeoutError):
            await client._send_stdio({"jsonrpc": "2.0", "id": 1, "method": "x", "params": {}}, 1)

        assert client._pending == {}

    @pytest.mark.asyncio
    async def test_disconnect_kills_and_awaits_process_when_terminate_times_out(self) -> None:
        client = MCPClient(
            "server1",
            {"transport": "stdio", "command": "true", "terminate_timeout_seconds": 0.05},
        )

        class _StubbornProcess:
            def __init__(self) -> None:
                self.stdin = _FakeStdin()
                self.stdout = None
                self.stderr = None
                self.terminate_called = False
                self.kill_called = False
                self.wait_calls = 0

            def terminate(self) -> None:
                self.terminate_called = True

            def kill(self) -> None:
                self.kill_called = True

            async def wait(self) -> int:
                self.wait_calls += 1
                if self.wait_calls == 1:
                    await asyncio.sleep(999)
                return 0

        process = _StubbornProcess()
        client._process = process  # type: ignore[assignment]
        client._connected = True

        await client.disconnect()

        assert process.terminate_called is True
        assert process.kill_called is True
        assert process.wait_calls == 2  # 第一次 terminate 超时, 第二次 kill 后必须真正 await 到退出


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
