"""memory_query_agent 工具 (M2, ROUTING_AND_AGENT_MESH.md §5.2/§6.1)。

向另一个 Agent 发起授权记忆查询 (受 visible_memory_scopes 裁剪)。默认 restricted;
M2 已接入 MeshActionBroker.memory_query。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.runtime.mesh.models import MeshLinkPolicy


class MemoryQueryAgentTool(Tool):
    @property
    def name(self) -> str:
        return "memory_query_agent"

    @property
    def description(self) -> str:
        return "向另一个 Agent 发起授权记忆查询 (仅限 Link 授予的可见记忆范围)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "description": "被查询的 Agent ID"},
                "query": {"type": "string", "description": "查询内容"},
            },
            "required": ["target_agent", "query"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """M2/P2: 经 MeshActionBroker.memory_query **同步**取回目标 Agent 的检索结果。

        P2: broker.memory_query 现在返回响应文本 (此前丢弃 bus.send 的 response,
        工具只能说"响应异步返回"而查询方永远拿不到结果); 策略按 Link 解析,
        visible_memory_scopes 由接收端 (main._deliver_to_agent) 真实裁剪。
        """
        broker = context.services.get("mesh_action_broker")
        if broker is None:
            return ToolResult(content="memory_query_agent 未接入 mesh_action_broker", is_error=True)
        policy: MeshLinkPolicy | None = context.services.get("mesh_link_policy")
        target = str(context.args.get("target_agent", ""))
        query = str(context.args.get("query", ""))
        agent_id = str(context.services.get("agent_id", ""))
        response = await broker.memory_query(agent_id, target, query, policy)
        if response is None:
            return ToolResult(
                content=f"查询 {target} 记忆失败 (Link 未配置或未授予 memory_query 权限)",
                is_error=True,
            )
        if not response.strip():
            return ToolResult(content=f"{target} 的可见记忆中没有与「{query[:50]}」相关的内容。")
        return ToolResult(content=f"【来自 {target} 的记忆】\n{response[:2000]}")
