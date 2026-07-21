"""ask_agent 工具: Agent 间通信 (ARCHITECTURE.md 3.3)。

经 InterAgentBus 与目标 Agent 通信，受 Link ACL 约束 (默认拒绝)。
"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


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
        """TODO(Day 43): 经 services["bus"] (InterAgentBus) 发送 request 消息并返回响应。

        - bus 未注入 → 返回错误 (当前 Agent 未启用互联)
        - Link 不存在 → InterAgentLinkDeniedError → 返回友好错误
        - 响应内容即目标 Agent 的回复文本
        """
        raise NotImplementedError("TODO(Day 43): 实现 ask_agent")
