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


# C2: 工具→scope 映射表。MCP stdio 桥接只校验扁平 api_token, 完全忽略
# tokens[] scope 模型, 让被限制为 usage:read 的 token 可通过 MCP 调
# agent_create/link_create/route_set_default 等写操作。映射表与 HTTP
# 端点的 scope_dependency 一一对应 (routes_agents.py 等), 保留一致性。
TOOL_SCOPE_MAP: dict[str, str] = {
    "agent_create": "agent:write",
    "agent_update_config": "agent:write",
    "agent_start": "agent:write",
    "agent_stop": "agent:write",
    "channel_bind_agent": "agent:write",
    "channel_unbind_agent": "agent:write",
    "route_set_default": "routing:write",
    "link_create": "link:write",
    "link_delete": "link:write",
    "plugin_set_enabled": "plugin:write",
    "message_send": "agent:write",
}


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
        parsed_tokens: list[Any] | None = None,
    ):
        self.services = services
        self.api_token = api_token
        self._agent_manager = agent_manager or services.get("agent_manager")
        self._router = router or services.get("router")
        self._bus = bus or services.get("bus")
        self._plugin_manager = plugin_manager or services.get("plugin_manager")
        # C2: parsed_tokens 为 None (未配置 tokens[]) 时回退到扁平 api_token,
        # 与 HTTP 端点行为一致 (向后兼容默认行为不变); 非 None 时按 scope 校验。
        self._parsed_tokens = parsed_tokens
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
        if method == "tools/call" and (self.api_token or self._parsed_tokens):
            auth_header = params.get("meta", {}).get("authorization", "") if isinstance(params, dict) else ""
            from isac.control.auth import extract_bearer

            token = extract_bearer(auth_header)
            # C2: parsed_tokens 配置时优先走 scope 校验; 否则回退扁平 api_token
            if self._parsed_tokens:
                matched_scope = self._find_token_scope(token)
                if matched_scope is None:
                    return self._error_response(request_id, -32001, "Unauthorized: invalid or missing token")
                # scope 校验下放到 _call_tool, 因 scope 与具体工具绑定
            elif self.api_token:
                from isac.control.auth import verify_token

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
            return self._error_response(request_id, -32603, "Internal server error")

    def _find_token_scope(self, token: str | None) -> frozenset[str] | None:
        """C2: 在 parsed_tokens 中查找匹配的 TokenScope, 返回其 scopes 或 None。

        时序安全: 用短路比较避免非常量时间, 但 token 校验本身不是敏感比较
        (token 已通过 Bearer Header 提供); 真正的敏感数据 (api_token) 在
        tokens[] 模型里已替换为 scoped tokens, 单个 token 暴露影响有限。
        """
        import hmac

        if not token or self._parsed_tokens is None:
            return None
        for ts in self._parsed_tokens:
            if hmac.compare_digest(token, ts.token):
                return ts.scopes
        return None

    def _check_tool_scope(self, tool_name: str, scopes: frozenset[str] | None) -> bool:
        """C2: 校验 scopes 是否包含 tool_name 对应的 scope。

        scopes=None 表示未启用 scope 模型 (parsed_tokens 为 None), 跳过校验。
        scopes 包含 "*" 表示全权限通配。
        """
        if scopes is None:
            return True  # 未启用 scope 模型, 由 token 认证兜底
        required = TOOL_SCOPE_MAP.get(tool_name)
        if required is None:
            return False  # 未知工具, 拒绝
        return required in scopes or "*" in scopes

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

    async def _check_scope_if_needed(self, name: str, params: dict[str, Any]) -> None:
        """C2: parsed_tokens 启用时按 tool→scope 映射校验 (抽自 _call_tool 降复杂度)。"""
        if self._parsed_tokens is None:
            return
        auth_header = params.get("meta", {}).get("authorization", "")
        from isac.control.auth import extract_bearer

        scopes = self._find_token_scope(extract_bearer(auth_header))
        if scopes is None:
            raise MCPError(-32001, "Unauthorized: invalid or missing token")
        if not self._check_tool_scope(name, scopes):
            required = TOOL_SCOPE_MAP.get(name, "unknown")
            raise MCPError(-32003, f"Forbidden: missing scope {required}")

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        """调用 MCP 工具, 委托到 AgentManager/Router/Bus。"""
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        # C2: parsed_tokens 启用时按 tool→scope 映射校验 (抽 helper 降复杂度)
        await self._check_scope_if_needed(name, params)
        if name == "agent_create" and self._agent_manager is not None:
            # CR3-L1: MCP 自动化创建同样走受限默认配置 (bash/task deny +
            # plugins_deny=["*"]), 调用方 arguments 里的能力字段被丢弃并告警。
            from isac.control.defaults import restricted_config_from_payload

            instance = await self._agent_manager.create(restricted_config_from_payload(args))
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
        # R2-④: 5 个新工具抽到模块级 helper 降 _call_tool 复杂度
        extra = await _call_r2_tools(name, args, self)
        if extra is not None:
            return extra
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


async def _call_r2_tools(name: str, args: dict[str, Any], server: Any) -> dict[str, Any] | None:
    """R2-④: 5 个声明未实现的工具 (channel_bind/unbind, agent_update_config,
    plugin_set_enabled, message_send) 的实现, 抽到模块级降 _call_tool 复杂度。

    返回 None 表示该工具不属于本 helper 或依赖缺失, 交给调用方兜底 raise。
    """
    if name == "channel_bind_agent" and server._router is not None:
        from isac.router.rules import ChannelBinding

        rules = server._router.get_rules()
        rules.bindings.append(ChannelBinding(
            platform=str(args.get("platform", "")), agent_id=str(args.get("agent_id", "")),
            group_id=args.get("group_id"), user_id=args.get("user_id"),
        ))
        server._router.set_rules(rules)
        return _text_result({"status": "bound"})
    if name == "channel_unbind_agent" and server._router is not None:
        rules = server._router.get_rules()
        plat, gid, uid = args.get("platform", ""), args.get("group_id"), args.get("user_id")
        before = len(rules.bindings)
        rules.bindings = [
            b for b in rules.bindings
            if not (b.platform == plat and b.group_id == gid and b.user_id == uid)
        ]
        server._router.set_rules(rules)
        return _text_result({"status": "unbound", "removed": before - len(rules.bindings)})
    if name == "agent_update_config" and server._agent_manager is not None:
        from pathlib import Path

        from isac.control.api.routes_agents import _do_patch_agent

        result = await _do_patch_agent(
            server._agent_manager, args.get("agent_id", ""),
            args.get("config", {}), args.get("if_match"), None, Path("data/agents"),
        )
        return _text_result(result)
    if name == "plugin_set_enabled" and server._agent_manager is not None:
        from pathlib import Path

        from isac.runtime.config import save_agent_config

        agent_id = args.get("agent_id", "")
        instance = await server._agent_manager.get(agent_id)
        if instance is None:
            raise MCPError(-32602, f"agent not found: {agent_id}")
        instance.config.plugins_allow = list(args.get("plugins_allow", ["*"]))
        instance.config.plugins_deny = list(args.get("plugins_deny", []))
        save_agent_config(Path("data/agents") / agent_id / "config.jsonc", instance.config)
        return _text_result({"status": "updated", "agent_id": agent_id})
    if name == "message_send" and server._agent_manager is not None:
        import time

        from isac.channel.model import ISACMessage
        from isac.gateway.models import Session
        from isac.utils.helpers import new_id, unix_now

        agent_id = args.get("agent_id", "")
        platform = str(args.get("platform", "mcp"))
        user_id = str(args.get("user_id", "mcp"))
        message = ISACMessage(
            msg_id=new_id("mcp"), platform=platform, timestamp=int(time.time()),
            user_id=user_id, user_name="", group_id=args.get("group_id"),
            content=str(args.get("content", "")),
        )
        session = Session(
            session_id=new_id("sess"), user_id=user_id, agent_id=agent_id,
            platform=platform, group_id=args.get("group_id"),
            is_group=args.get("group_id") is not None, created_at=unix_now(),
        )
        reply = await server._agent_manager.handle_message_serialized(agent_id, message, session, None)
        return _text_result({"status": "sent", "reply": reply or ""})
    return None


class MCPError(Exception):
    """MCP 协议错误 (JSON-RPC 错误码)。"""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
