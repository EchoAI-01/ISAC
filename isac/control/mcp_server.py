"""ISAC MCP Server: ISAC 作为 MCP 服务端 (ARCHITECTURE.md 3.9 / SPECIFICATION.md 4.5)。

让外部系统用 MCP 客户端自动化管理 ISAC，与 Admin API 共用认证。
"""

from __future__ import annotations

from typing import Any

# 管理工具清单 (SPECIFICATION.md 4.5)
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
    """ISAC MCP 服务端。

    TODO(Day 74): MCP 协议实现 (stdio/SSE)，工具全部委托 AgentManager/Router/Bus。
    """

    def __init__(self, services: dict[str, Any]):
        self.services = services

    async def serve(self) -> None:
        raise NotImplementedError("TODO(Day 74): 实现 MCP Server")
