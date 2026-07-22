"""ask_agent 工具: Agent 间通信 (ARCHITECTURE.md 3.3)。

经 InterAgentBus 与目标 Agent 通信，受 Link ACL 约束 (默认拒绝)。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.exceptions import InterAgentLinkDeniedError
from isac.core.types import ToolResult
from isac.runtime.bus import InterAgentMessage


class AskAgentTool(Tool):
    """向另一个 Agent 提问 (需要已配置互联 Link)。"""

    @property
    def name(self) -> str:
        return "ask_agent"

    @property
    def description(self) -> str:
        return "向另一个 Agent 提问并获取回复 (仅限已互联的 Agent)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "target_agent": {"type": "string", "description": "目标 Agent ID"},
                "question": {"type": "string", "description": "问题内容"},
            },
            "required": ["target_agent", "question"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """经 services["bus"] 发送 request 消息并返回响应。"""
        bus = context.services.get("bus")
        if bus is None:
            return ToolResult(content="当前 Agent 未启用互联总线，无法调用其他 Agent。", is_error=True)

        target_agent = str(context.args.get("target_agent", "")).strip()
        question = str(context.args.get("question", "")).strip()
        if not target_agent or not question:
            return ToolResult(content="ask_agent 缺少 target_agent 或 question。", is_error=True)

        from_agent = getattr(context.agent_context.session, "agent_id", "")
        if not from_agent:
            return ToolResult(content="当前会话缺少 agent_id，无法发起 Agent 互联。", is_error=True)

        message = InterAgentMessage(
            from_agent=from_agent,
            to_agent=target_agent,
            type="request",
            content=question,
            context={"session_id": getattr(context.agent_context.session, "session_id", "")},
        )
        try:
            response = await bus.send(message)
        except InterAgentLinkDeniedError:
            return ToolResult(content=f"无权与 Agent {target_agent} 通信，请先配置 InterAgentLink。", is_error=True)
        except Exception as exc:
            return ToolResult(content=f"Agent 互联调用失败：{exc}", is_error=True)

        if response is None:
            return ToolResult(content=f"已向 Agent {target_agent} 发送请求，但未返回响应。")
        return ToolResult(content=response.content)
