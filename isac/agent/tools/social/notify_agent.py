"""notify_agent 工具 (M2, ROUTING_AND_AGENT_MESH.md §5.2)。

单向通知另一个 Agent (不等待响应)。默认 restricted (LLM 可见但需注入
mesh_action_broker + policy); M2 已接入 MeshActionBroker.notify。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.runtime.mesh.models import MeshLinkPolicy


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
        """M2: 经 MeshActionBroker.notify → InterAgentBus 发 NOTIFY 消息。

        P2: 策略按 (from, to) 从 Link 解析 (broker.policy_for), 不再依赖单值
        services["mesh_link_policy"] —— 显式注入时仍优先用它 (测试/特殊场景)。
        """
        broker = context.services.get("mesh_action_broker")
        if broker is None:
            return ToolResult(content="notify_agent 未接入 mesh_action_broker", is_error=True)
        policy: MeshLinkPolicy | None = context.services.get("mesh_link_policy")
        target = str(context.args.get("target_agent", ""))
        content = str(context.args.get("content", ""))
        agent_id = str(context.services.get("agent_id", ""))
        ok = await broker.notify(agent_id, target, content, policy)
        if not ok:
            return ToolResult(
                content=f"通知 {target} 失败 (Link 未配置或未授予 notify 权限)", is_error=True
            )
        return ToolResult(content=f"已通知 {target}: {content[:50]}")
