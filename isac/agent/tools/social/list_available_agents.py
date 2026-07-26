"""list_available_agents 工具 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

列出当前 Agent 可协作的对端 (已配置 Link)。默认 restricted; M2 已接入
MeshActionBroker.list_available。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class ListAvailableAgentsTool(Tool):
    @property
    def name(self) -> str:
        return "list_available_agents"

    @property
    def description(self) -> str:
        return "列出当前 Agent 可协作的其他 Agent (已配置互联 Link 的对端)"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, context: ToolContext) -> ToolResult:
        """M2: 经 MeshActionBroker.list_available 从 Link 表过滤可见对端。"""
        broker = context.services.get("mesh_action_broker")
        if broker is None:
            return ToolResult(content="list_available_agents 未接入 mesh_action_broker", is_error=True)
        agent_id = str(context.services.get("agent_id", ""))
        peers = broker.list_available(agent_id)
        if not peers:
            return ToolResult(content="当前 Agent 无可协作的对端 (未配置 Link 或全部 disabled)")
        return ToolResult(content="可协作的 Agent: " + ", ".join(peers))
