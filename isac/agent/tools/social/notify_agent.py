"""notify_agent 工具骨架 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

单向通知另一个 Agent (不等待响应)。默认 deny (definitions() 过滤, LLM 不可见),
M2 实现节点接入 MeshActionBroker.notify 后改为 restricted。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class NotifyAgentTool(Tool):
    @property
    def name(self) -> str:
        return "notify_agent"

    @property
    def description(self) -> str:
        return "向另一个 Agent 发送单向通知 (仅限已互联的 Agent, 不等待回复)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "description": "目标 Agent ID"},
                "content": {"type": "string", "description": "通知内容"},
            },
            "required": ["target_agent", "content"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """TODO(M2): 经 MeshActionBroker.notify → InterAgentBus 发 NOTIFY 消息。

        骨架阶段: 默认 deny 不会被 LLM 调用; 若显式启用则返回未实现提示。
        """
        return ToolResult(content="notify_agent 尚未实现 (M2 待落地)。", is_error=True)
