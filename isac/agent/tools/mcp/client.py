"""MCP Client: 连接外部 MCP 服务器, 将其工具桥接为 ISAC Tool。

支持两种传输: stdio (子进程) + HTTP/SSE。
按 Agent 配置 (AgentConfig.mcp_servers) 决定可用 Server (启用矩阵)。
"""

from __future__ import annotations

import asyncio
import json
import os
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
        # 后台读取任务 (disconnect 时需要 cancel + await, 避免任务泄漏)
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stdio_request_timeout = float(config.get("request_timeout_seconds", 30))
        self._terminate_timeout = float(config.get("terminate_timeout_seconds", 5))

    async def connect(self) -> None:
        """建立连接 (stdio 子进程或 HTTP)。

        CR3-L8: transport="sse" 此前被静默当作普通 HTTP POST 处理 (无任何 SSE
        流式语义), 对配置方是误导; 在真正实现 SSE 之前显式拒绝, 提示改用 http/stdio。
        """
        if self._transport == "stdio":
            await self._connect_stdio()
        elif self._transport == "http":
            await self._connect_http()
        elif self._transport == "sse":
            raise ValueError(
                f"不支持的 MCP 传输: sse (Server {self.server_name} 的 SSE 模式尚未实现, "
                "请改用 transport=\"http\" 或 \"stdio\")"
            )
        else:
            raise ValueError(f"不支持的 MCP 传输: {self._transport}")
        # N5b 批次D 项4: MCP 握手 (initialize + initialized)。规范 server 要求握手后
        # 才响应 tools/list, 未握手则恒 0 工具 (Critical)。先设 _connected=True 让
        # stdio reader 循环跑 (其 while 条件依赖此标志); 握手失败降级仍 connected。
        self._connected = True
        await self._handshake()
        logger.info("MCP Client 已连接", server=self.server_name, transport=self._transport)

    async def _connect_stdio(self) -> None:
        """启动子进程 + 拿 stdin/stdout 流。"""
        command = self.config.get("command")
        args = list(self.config.get("args", []))
        # 2026-08-19 (M6): 此前直接把 config.env (默认 {}) 作为子进程 env —— 空 dict
        # 会让 MCP 子进程拿到**完全为空**的环境 (无 PATH/HOME 等), 绝大多数命令
        # 无法启动。改为继承 os.environ 并用 config.env 覆盖 (自定义键优先)。
        env = {**os.environ, **dict(self.config.get("env", {}))}
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
        # 启动后台读 stdout/stderr 的任务 (任务引用必须保存, disconnect 时才能 cancel+await)
        self._stdout_task = asyncio.create_task(self._read_stdout_loop())
        self._stderr_task = asyncio.create_task(self._read_stderr_loop())

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
                server_name=self.server_name,
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                parameters=tool.get("inputSchema", {"type": "object"}),
            )
            for tool in tools_list
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """转发 tools/call 到 MCP Server。

        M5: 调用前做存活检测, stdio 子进程已崩溃时自动重连一次 —— 此前崩溃无感知,
        此后该 server 全部调用恒失败且无恢复路径。
        """
        if not await self.ensure_connected():
            return ToolResult(
                content=f"MCP server {self.server_name} 不可用 (未连接或重连失败), 无法调用 {name}",
                is_error=True,
            )
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

    def is_alive(self) -> bool:
        """M5 健康检测: 已连接且传输层存活。

        stdio: 子进程存活 (returncode is None); http: client 未关闭。
        未连接/已主动断开返回 False。
        """
        if not self._connected:
            return False
        if self._transport == "stdio":
            return self._process is not None and self._process.returncode is None
        return self._http_client is not None

    async def ensure_connected(self) -> bool:
        """M5: 保证可用 —— 已崩溃 (曾连接但传输层死亡) 时自动重连一次。

        从未连接/已主动 disconnect 的不自动重连 (语义上无人期望它活着)。
        重连成功返回 True; 失败记日志返回 False (调用方据此返回明确错误)。
        """
        if self.is_alive():
            return True
        if not self._connected:
            return False
        logger.warning("MCP server 连接已丢失, 尝试重连", server=self.server_name)
        try:
            await self.disconnect()  # 清理残留进程/客户端状态
            await self.connect()  # 重连 (含握手)
            logger.info("MCP server 重连成功", server=self.server_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP server 重连失败", server=self.server_name, error=str(exc))
            return False

    async def disconnect(self) -> None:
        """断开连接 (kill 子进程 / 关闭 httpx)。"""
        self._connected = False
        for task in (self._stdout_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._stdout_task = None
        self._stderr_task = None
        if self._process is not None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=self._terminate_timeout)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
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

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """发送 JSON-RPC notification (无 id, 单向, 不等响应)。"""
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        if self._transport == "stdio":
            if self._process is None or self._process.stdin is None:
                raise RuntimeError("MCP 子进程未启动")
            line = (json.dumps(notification, ensure_ascii=False) + "\n").encode("utf-8")
            self._process.stdin.write(line)
            await self._process.stdin.drain()
        else:
            if self._http_client is None:
                raise RuntimeError("MCP HTTP 未连接")
            await self._http_client.post("/", json=notification)

    async def _handshake(self) -> None:
        """MCP 规范握手: initialize request → 校验 → notifications/initialized。

        规范 server 在收到 initialize + initialized 后才响应 tools/list; 未握手则
        tools/list 无响应 → 30s 超时 → 0 工具注册 (D4 Critical)。
        容错: initialize 超时/失败时仅 warning 不 raise (向后兼容非规范 server/自测桩);
        规范 server 受益于握手, 非规范 server 仍走原降级路径。
        """
        try:
            await asyncio.wait_for(
                self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "isac", "version": "1.0.0"},
                }),
                timeout=5.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MCP initialize 握手未完成 (server 可能非规范, 继续降级)",
                server=self.server_name, error=str(exc),
            )
            return
        try:
            await self._send_notification("notifications/initialized", {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP initialized 通知发送失败", server=self.server_name, error=str(exc))

    async def _send_stdio(self, request: dict[str, Any], request_id: int) -> dict[str, Any]:
        """stdio 模式: 写入 stdin, 等 stdout 响应。

        超时或被取消时必须清理 _pending, 否则每次超时都会永久残留一个 Future (内存泄漏)。
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP 子进程未启动")
        line = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = fut
        try:
            self._process.stdin.write(line)
            await self._process.stdin.drain()
            return await asyncio.wait_for(fut, timeout=self._stdio_request_timeout)
        finally:
            self._pending.pop(request_id, None)

    async def _send_http(self, request: dict[str, Any]) -> dict[str, Any]:
        """HTTP 模式: POST 请求 + 响应。

        CR3-L8: 补 HTTP 状态码检查 —— 此前 4xx/5xx 的错误页会被直接 .json()
        (通常抛 JSONDecodeError 或返回误导性的错误体)。getattr 防御式取
        status_code 兼容测试注入的最小 mock 响应对象。
        """
        if self._http_client is None:
            raise RuntimeError("MCP HTTP 未连接")
        response = await self._http_client.post("/", json=request)
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code >= 400:
            body = str(getattr(response, "text", ""))[:200]
            raise RuntimeError(f"MCP Server {self.server_name} HTTP {status_code}: {body}")
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
                # Fix-124: id 非数字 (脏响应/非规范 server) 时 int() 会抛异常 —— 此前冒泡
                # 到下方宽 except 被误记为"非 JSON 行"。显式捕获, 非数字 id 只是匹配不到
                # 在途请求, 跳过即可, 不影响 reader 继续消费。
                fut = None
                if request_id is not None:
                    try:
                        fut = self._pending.pop(int(request_id), None)
                    except (TypeError, ValueError):
                        fut = None
                if fut is not None and not fut.done():
                    fut.set_result(response)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                # N5b 批次D 项5: 脏输出 (非 JSON 行, 如 server 日志/banner) 不应
                # break 退出 reader —— 否则 _pending 里所有在途 future 永无人 set_result
                # → _send_stdio wait_for 全部 30s 超时, 此后该 server 所有调用恒超时,
                # 且 stdout 缓冲无人消费致子进程反压卡死。改为 continue 跳过该行继续读。
                logger.debug("MCP stdout 跳过非 JSON 行", server=self.server_name, error=str(exc))
                continue

    async def _read_stderr_loop(self) -> None:
        """stdio 模式: 持续消费 stderr, 避免管道缓冲区填满导致子进程阻塞。仅记录日志。"""
        if self._process is None or self._process.stderr is None:
            return
        while True:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                logger.debug(
                    "MCP stderr",
                    server=self.server_name,
                    line=line.decode("utf-8", errors="replace").rstrip(),
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP stderr 读异常", server=self.server_name, error=str(exc))
                break


class MCPToolBridge(Tool):
    """把 MCP 工具桥接为 ISAC Tool。"""

    def __init__(
        self,
        client: MCPClient,
        server_name: str,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ):
        self._client = client
        self._server_name = server_name
        # N5b 批次C C9: 注册名加 mcp:{server}:{tool} 前缀, 防同名 MCP 工具顶替内置
        # 工具 (如 MCP 的 bash/read_file 覆盖内置同名); 调 server 时用原名。
        self._tool_name = name
        self._name = f"mcp:{server_name}:{name}"
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
        """转发到 MCPClient.call_tool (用原名, 不带 mcp: 前缀)。"""
        return await self._client.call_tool(self._tool_name, dict(context.args))
