"""memory_query_agent 工具骨架 (M2, ROUTING_AND_AGENT_MESH.md §5.2/§6.1)。

向另一个 Agent 发起授权记忆查询 (受 visible_memory_scopes 裁剪)。默认 deny
(LLM 不可见), M2 实现节点接入 MeshActionBroker.memory_query 后改为 restricted。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


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
        """TODO(M2): 经 MeshActionBroker.memory_query, 按 visible_memory_scopes 裁剪范围。

        骨架阶段: 默认 deny 不会被 LLM 调用; 若显式启用则返回未实现提示。
        """
        return ToolResult(content="memory_query_agent 尚未实现 (M2 待落地)。", is_error=True)
