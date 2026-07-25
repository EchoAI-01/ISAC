"""wait 工具: 暂缓回复，等待更多消息。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class WaitTool(Tool):
    @property
    def name(self) -> str:
        return "wait"

    @property
    def description(self) -> str:
        return "暂时不回复，等待对方继续说"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"seconds": {"type": "integer", "description": "等待秒数", "default": 5}},
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """返回非阻塞等待意图。

        TODO(L2): conversation.enabled 时改为向本会话 ConversationRuntime 注册
        WaitState (runtime.enter_wait),由 timeout / message / proactive 结束并回填
        wait 工具结果;骨架阶段仍返回意图字符串,保持现有行为。
        """
        seconds = max(0, int(context.args.get("seconds", 5) or 5))
        session_id = getattr(context.agent_context.session, "session_id", "")
        return ToolResult(content=f"已记录等待意图：等待 {seconds} 秒或等待对方继续说。session_id={session_id}")
