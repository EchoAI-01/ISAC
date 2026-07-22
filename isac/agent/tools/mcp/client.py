"""MCP Client: 连接外部 MCP 服务器, 将其工具桥接为 ISAC Tool。

支持两种传输: stdio (子进程) + HTTP/SSE。
按 Agent 配置 (AgentConfig.mcp_servers) 决定可用 Server (启用矩阵)。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class MCPClient:
    """MCP 服务器客户端。

    支持:
    - connect(): 建立 stdio 子进程或 HTTP 连接
    - list_tools(): 发现 MCP 工具并桥接为 ISAC Tool
    - call_tool(name, args): 转发调用 + 错误处理
    - disconnect(): 关闭连接
    """

    def __init__(self, server_name: str, config: dict[str, Any]):
        self.server_name = server_name
        self.config = config
        self._transport = config.get("transport", "stdio")
        self._connected = False
        self._process: asyncio.subprocess.Process | None = None
        self._http_client: Any = None
        self._url: str = ""
        self._token: str = ""
        self._request_id = 0
        # stdio 协议下的 reader/writer 缓冲
        self._stdout_reader: asyncio.StreamReader | None = None
        self._stdin_writer: asyncio.StreamWriter | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    async def connect(self) -> None:
        """建立连接 (stdio 子进程或 HTTP)。"""
        if self._transport == "stdio":
            await self._connect_stdio()
        elif self._transport in ("http", "sse"):
            await self._connect_http()
        else:
            raise ValueError(f"不支持的 MCP 传输: {self._transport}")
        self._connected = True
        logger.info("MCP Client 已连接", server=self.server_name, transport=self._transport)

    async def _connect_stdio(self) -> None:
        """启动子进程 + 拿 stdin/stdout 流。"""
        command = self.config.get("command")
        args = list(self.config.get("args", []))
        env = self.config.get("env", {})
        if not command:
            raise ValueError("stdio 传输需要 command 配置")
        try:
            self._process = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"MCP 子进程启动失败: {exc}") from exc
        # 启动后台读 stdout 的任务
        asyncio.create_task(self._read_stdout_loop())

    async def _connect_http(self) -> None:
        """建立 HTTP/SSE 连接 (惰性 httpx)。"""
        self._url = str(self.config.get("url", ""))
        self._token = str(self.config.get("token", ""))
        if not self._url:
            raise ValueError("http/sse 传输需要 url 配置")
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("MCP HTTP 模式需要 httpx") from exc
        self._http_client = httpx.AsyncClient(
            base_url=self._url,
            headers={"Authorization": f"Bearer {self._token}"} if self._token else {},
            timeout=30,
        )

    async def list_tools(self) -> list[Tool]:
        """发现 MCP 工具并桥接为 ISAC Tool。"""
        if not self._connected:
            raise RuntimeError("MCP Client 未连接, 无法 list_tools")
        response = await self._send_request("tools/list", {})
        tools_list = response.get("result", {}).get("tools", [])
        return [
            MCPToolBridge(
                client=self,
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=tool.get("inputSchema", {"type": "object"}),
            )
            for tool in tools_list
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """转发 tools/call 到 MCP Server。"""
        if not self._connected:
            return ToolResult(content=f"MCP Client 未连接, 无法调用 {name}", is_error=True)
        response = await self._send_request(
            "tools/call",
            {"name": name, "arguments": args},
        )
        if "error" in response:
            err = response["error"]
            return ToolResult(
                content=f"MCP 工具 {name} 调用失败: {err.get('message', '')}",
                is_error=True,
            )
        result = response.get("result", {})
        content_blocks = result.get("content", [])
        text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
        return ToolResult(content="\n".join(text_parts))

    async def disconnect(self) -> None:
        """断开连接 (kill 子进程 / 关闭 httpx)。"""
        self._connected = False
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                self._process.kill()
            except ProcessLookupError:
                pass
            self._process = None
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        # 取消所有 pending future
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("MCP Client 已断开", server=self.server_name)

    # ── JSON-RPC 传输层 ────────────────────────────────────

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON-RPC 请求并等待响应。"""
        self._request_id += 1
        request_id = self._request_id
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        if self._transport == "stdio":
            return await self._send_stdio(request, request_id)
        return await self._send_http(request)

    async def _send_stdio(self, request: dict[str, Any], request_id: int) -> dict[str, Any]:
        """stdio 模式: 写入 stdin, 等 stdout 响应。"""
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP 子进程未启动")
        line = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        self._process.stdin.write(line)
        await self._process.stdin.drain()
        return await asyncio.wait_for(fut, timeout=30)

    async def _send_http(self, request: dict[str, Any]) -> dict[str, Any]:
        """HTTP 模式: POST 请求 + 响应。"""
        if self._http_client is None:
            raise RuntimeError("MCP HTTP 未连接")
        response = await self._http_client.post("/", json=request)
        return response.json()

    async def _read_stdout_loop(self) -> None:
        """stdio 模式: 后台读 stdout NDJSON, 分发到 pending future。"""
        if self._process is None or self._process.stdout is None:
            return
        while self._connected:
            try:
                line = await self._process.stdout.readline()
                if not line:
                    break
                response = json.loads(line.decode("utf-8"))
                request_id = response.get("id")
                fut = self._pending.pop(int(request_id), None) if request_id is not None else None
                if fut is not None and not fut.done():
                    fut.set_result(response)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP stdout 读异常", server=self.server_name, error=str(exc))
                break


class MCPToolBridge(Tool):
    """把 MCP 工具桥接为 ISAC Tool。"""

    def __init__(
        self,
        client: MCPClient,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ):
        self._client = client
        self._name = name
        self._description = description
        self._parameters = parameters

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    async def execute(self, context: ToolContext) -> ToolResult:
        """转发到 MCPClient.call_tool。"""
        return await self._client.call_tool(self._name, dict(context.args))
