"""list_available_agents 工具骨架 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

列出当前 Agent 可协作的对端 (已配置 Link)。默认 deny (LLM 不可见),
M2 实现节点接入 MeshActionBroker.list_available 后改为 allow/restricted。
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

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(M2): 经 MeshActionBroker.list_available 从 Link 表过滤可见对端。

        骨架阶段: 默认 deny 不会被 LLM 调用; 若显式启用则返回空列表提示。
        """
        return ToolResult(content="list_available_agents 尚未实现 (M2 待落地)。", is_error=True)
