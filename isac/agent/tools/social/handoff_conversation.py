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
        """M2/P2: 摘要投递 + **会话归属真实转移**。

        此前只经 bus 发一条 HANDOFF 消息, Router 侧无任何变化 —— 后续消息仍路由
        给移交方, "移交"只是聊天。P2 补上归属转移: 摘要投递成功后在 MessageRouter
        登记 handoff 覆盖 (platform + 群/私聊主体 → 接手 Agent), 该会话后续消息
        直接路由给接手方 (优先级最高; 内存态, 重启回落常规规则)。
        """
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
                content=f"移交 {target} 失败 (Link 未配置或未授予 handoff 权限)", is_error=True
            )
        # P2: 会话归属转移 —— router 经 services 注入 (无 router 时降级为仅投递摘要)
        router = context.services.get("router")
        session = context.agent_context.session
        if router is not None and session is not None:
            router.set_handoff(
                getattr(session, "platform", ""),
                getattr(session, "group_id", None),
                getattr(session, "user_id", ""),
                target,
            )
            return ToolResult(content=f"已移交会话给 {target} (后续消息由其接手), 摘要: {summary[:50]}")
        return ToolResult(content=f"已通知 {target} 接手 (摘要已送达), 摘要: {summary[:50]}")
