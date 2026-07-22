"""MCP Client: 连接外部 MCP 服务器，将其工具桥接为 ISAC Tool。

按 Agent 配置 (AgentConfig.mcp_servers) 决定可用的 MCP Server (启用矩阵)。
"""

from __future__ import annotations

from typing import Any

from isac.agent.tools.base import Tool
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class MCPClient:
    """MCP 服务器客户端。

    [桩] 待实现:
    - 连接 MCP Server (stdio / SSE)
    - 发现工具列表并转换为 ISAC Tool 定义
    - 调用转发 + 错误处理
    """

    def __init__(self, server_name: str, config: dict[str, Any]):
        self.server_name = server_name
        self.config = config

    async def connect(self) -> None:
        raise NotImplementedError("MCPClient.connect 尚未实现")

    async def list_tools(self) -> list[Tool]:
        """发现 MCP 工具并桥接为 ISAC Tool。"""
        raise NotImplementedError("MCPClient.list_tools 尚未实现")

    async def disconnect(self) -> None:
        raise NotImplementedError("MCPClient.disconnect 尚未实现")
