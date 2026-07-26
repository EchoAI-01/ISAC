"""handoff_conversation 工具 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

把当前会话移交给另一个 Agent (附会话摘要)。默认 restricted; M2 已接入
MeshActionBroker.handoff。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.runtime.mesh.models import MeshLinkPolicy


class HandoffConversationTool(Tool):
    @property
    def name(self) -> str:
        return "handoff_conversation"

    @property
    def description(self) -> str:
        return "把当前会话移交给另一个 Agent 接手 (仅限已互联的 Agent)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "description": "接手的 Agent ID"},
                "summary": {"type": "string", "description": "移交时附带的会话摘要"},
            },
            "required": ["target_agent", "summary"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """M2: 经 MeshActionBroker.handoff → InterAgentBus 发 HANDOFF + 摘要交接。"""
        broker = context.services.get("mesh_action_broker")
        if broker is None:
            return ToolResult(content="handoff_conversation 未接入 mesh_action_broker", is_error=True)
        policy: MeshLinkPolicy | None = context.services.get("mesh_link_policy")
        target = str(context.args.get("target_agent", ""))
        summary = str(context.args.get("summary", ""))
        agent_id = str(context.services.get("agent_id", ""))
        ok = await broker.handoff(agent_id, target, summary, policy)
        if not ok:
            return ToolResult(
                content=f"移交 {target} 失败 (ACL 拒绝或 Link 未配置)", is_error=True
            )
        return ToolResult(content=f"已移交会话给 {target}, 摘要: {summary[:50]}")
