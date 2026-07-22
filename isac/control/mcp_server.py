"""ISAC MCP Server: ISAC 作为 MCP 服务端 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.5)。

让外部系统用 MCP 客户端自动化管理 ISAC，与 Admin API 共用认证。

MCP (Model Context Protocol) 简化实现:
- stdio 传输 (主模式, stdin/stdout NDJSON)
- JSON-RPC 2.0 协议 (methods: initialize/tools/list/tools/call)
- 工具清单委托 AgentManager / MessageRouter / InterAgentBus / PluginManager
- 与 Admin API 共用 api_token 认证

完整 MCP SDK (官方 mcp 包) 未引入, 此实现是 stdio JSON-RPC 桥接版本。
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.plugin.runtime.manager import PluginManager
    from isac.router.router import MessageRouter
    from isac.runtime.bus import InterAgentBus
    from isac.runtime.manager import AgentManager

logger = get_logger(__name__)


# 工具清单 (SPECIFICATION.md 4.5)
MCP_TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "agent_create", "description": "创建 Agent"},
    {"name": "agent_update_config", "description": "修改 Agent 参数"},
    {"name": "agent_start", "description": "启动 Agent"},
    {"name": "agent_stop", "description": "停止 Agent"},
    {"name": "channel_bind_agent", "description": "绑定 Channel ↔ Agent"},
    {"name": "channel_unbind_agent", "description": "解绑 Channel ↔ Agent"},
    {"name": "route_set_default", "description": "设置平台默认 Agent"},
    {"name": "link_create", "description": "创建互联 Link"},
    {"name": "link_delete", "description": "删除互联 Link"},
    {"name": "plugin_set_enabled", "description": "插件启用矩阵"},
    {"name": "message_send", "description": "以某 Agent 身份发送消息 (自动化流程入口)"},
]


class ISACMCPServer:
    """ISAC MCP 服务端 (stdio + JSON-RPC 2.0)。

    [桩] stdio 协议实现已完成, 工具全部委托 AgentManager/Router/Bus。
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        services: dict[str, Any],
        *,
        api_token: str = "",
        agent_manager: AgentManager | None = None,
        router: MessageRouter | None = None,
        bus: InterAgentBus | None = None,
        plugin_manager: PluginManager | None = None,
    ):
        self.services = services
        self.api_token = api_token
        self._agent_manager = agent_manager or services.get("agent_manager")
        self._router = router or services.get("router")
        self._bus = bus or services.get("bus")
        self._plugin_manager = plugin_manager or services.get("plugin_manager")
        self._initialized = False

    async def serve_stdio(
        self,
        reader: asyncio.StreamReader | None = None,
        writer: asyncio.StreamWriter | None = None,
    ) -> None:
        """主循环: 读 stdin NDJSON → 处理 → 写 stdout NDJSON。

        reader/writer 为 None 时使用 sys.stdin/sys.stdout (适合被 MCP 客户端 fork)。
        """
        if reader is None or writer is None:
            await self._serve_native_stdio()
            return

        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                request = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                await self._send_error(writer, None, -32700, f"Parse error: {exc}")
                continue
            response = await self._handle_request(request)
            if response is not None:
                writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()

    async def _serve_native_stdio(self) -> None:
        """直接用 sys.stdin/stdout.buffer 的简化实现。"""
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                break
            try:
                request = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                err = self._error_response(None, -32700, f"Parse error: {exc}")
                sys.stdout.buffer.write(
                    (json.dumps(err, ensure_ascii=False) + "\n").encode("utf-8")
                )
                sys.stdout.buffer.flush()
                continue
            response = await self._handle_request(request)
            if response is not None:
                sys.stdout.buffer.write(
                    (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                )
                sys.stdout.buffer.flush()

    async def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """JSON-RPC 2.0 分发: 返回 response 或 None (通知不响应)。"""
        request_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        # protocol-level 方法 (initialize / tools/list / shutdown) 不需要 token
        # tools/call 需要 token 认证
        if method == "tools/call" and self.api_token:
            auth_header = params.get("meta", {}).get("authorization", "") if isinstance(params, dict) else ""
            from isac.control.auth import extract_bearer, verify_token

            token = extract_bearer(auth_header)
            if not verify_token(token, self.api_token):
                return self._error_response(request_id, -32001, "Unauthorized: invalid or missing token")

        try:
            result = await self._dispatch(method, params)
            if request_id is None:
                return None  # notification 不响应
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except MCPError as exc:
            return self._error_response(request_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 防御
            logger.error("MCP 请求处理异常", method=method, error=str(exc), exc_info=True)
            return self._error_response(request_id, -32603, f"Internal error: {exc}")

    async def _dispatch(self, method: str, params: dict | list) -> Any:
        """MCP 方法分发。"""
        params_dict = params if isinstance(params, dict) else {}
        if method == "initialize":
            self._initialized = True
            return {
                "protocolVersion": self.PROTOCOL_VERSION,
                "serverInfo": {"name": "isac-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        if method == "tools/list":
            tools = [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "inputSchema": {"type": "object"},
                }
                for s in MCP_TOOL_SPECS
            ]
            return {"tools": tools}
        if method == "tools/call":
            return await self._call_tool(params_dict)
        if method == "shutdown":
            return None
        raise MCPError(-32601, f"Method not found: {method}")

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具, 委托到 AgentManager/Router/Bus。"""
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        if name == "agent_create" and self._agent_manager is not None:
            from isac.runtime.config import AgentConfig

            instance = await self._agent_manager.create(AgentConfig(**args))
            return _text_result({"agent_id": instance.agent_id, "status": instance.status})
        if name == "agent_start" and self._agent_manager is not None:
            await self._agent_manager.start(args.get("agent_id", ""))
            return _text_result({"agent_id": args.get("agent_id"), "status": "running"})
        if name == "agent_stop" and self._agent_manager is not None:
            await self._agent_manager.stop(args.get("agent_id", ""))
            return _text_result({"agent_id": args.get("agent_id"), "status": "stopped"})
        if name == "link_create" and self._bus is not None:
            from isac.runtime.bus import InterAgentLink

            self._bus.add_link(InterAgentLink(**args))
            return _text_result({"status": "added"})
        if name == "link_delete" and self._bus is not None:
            self._bus.remove_link(args.get("from_agent", ""), args.get("to_agent", ""))
            return _text_result({"status": "removed"})
        if name == "route_set_default" and self._router is not None:
            rules = self._router.get_rules()
            rules.default_agents[args.get("platform", "")] = args.get("agent_id", "")
            self._router.set_rules(rules)
            return _text_result({"status": "updated"})
        raise MCPError(-32602, f"Unknown tool or missing dependency: {name}")

    async def _send_error(self, writer: asyncio.StreamWriter, request_id: Any, code: int, message: str) -> None:
        response = self._error_response(request_id, code, message)
        writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()

    @staticmethod
    def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


def _text_result(payload: dict[str, Any]) -> dict[str, Any]:
    """构造 MCP tools/call 返回格式 (content 数组带 text 块)。"""
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


class MCPError(Exception):
    """MCP 协议错误 (JSON-RPC 错误码)。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
