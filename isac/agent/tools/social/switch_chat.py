"""switch_chat 工具: 主动切换话题 (ARCHITECTURE.md 3.5)。

更新会话话题状态 (写入 services["session_topic"]) 并返回过渡语供 LLM 接续。
若未注入 session_topic 服务, 返回友好错误。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class SwitchChatTool(Tool):
    @property
    def name(self) -> str:
        return "switch_chat"

    @property
    def description(self) -> str:
        return "主动切换当前聊天话题"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"topic": {"type": "string", "description": "新话题"}},
            "required": ["topic"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        topic = str(context.args.get("topic", "") or "").strip()
        if not topic:
            return ToolResult(content="switch_chat 缺少 topic。", is_error=True)

        session_topic = context.services.get("session_topic")
        session_id = getattr(context.agent_context.session, "session_id", "")
        if session_topic is None:
            return ToolResult(content="当前未启用会话话题管理能力，无法切换话题。", is_error=True)

        try:
            await session_topic.set(session_id, topic)
        except Exception as exc:
            return ToolResult(content=f"话题切换失败: {exc}", is_error=True)

        return ToolResult(
            content=(
                f"已切换会话话题到「{topic}」。请在下一轮回复中使用自然的过渡语，"
                "不要直接向用户声明已执行话题切换动作。"
            )
        )
