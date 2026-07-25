"""handoff_conversation 工具骨架 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

把当前会话移交给另一个 Agent (附会话摘要)。默认 deny (LLM 不可见),
M2 实现节点接入 MeshActionBroker.handoff 后改为 restricted。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


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
            "required": ["target_agent"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(M2): 经 MeshActionBroker.handoff → InterAgentBus 发 HANDOFF + 摘要交接。

        骨架阶段: 默认 deny 不会被 LLM 调用; 若显式启用则返回未实现提示。
        """
        return ToolResult(content="handoff_conversation 尚未实现 (M2 待落地)。", is_error=True)
