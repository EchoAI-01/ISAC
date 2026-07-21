"""/focus 命令: 开启/关闭 Focus Mode (ARCHITECTURE.md 3.7)。"""

from __future__ import annotations

from isac.channel.model import ISACMessage
from isac.commands.base import Command
from isac.core.types import AgentContext


class FocusCommand(Command):
    """专注模式开关。需要 gating 实例 (经 services 注入) 时生效。"""

    @property
    def name(self) -> str:
        return "focus"

    @property
    def description(self) -> str:
        return "开启/关闭专注模式 (Bot 在该会话积极参与)"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """TODO(Day 40): 经注入的 GatingSystem.focus_mode enter/exit。"""
        raise NotImplementedError("TODO(Day 40): 实现 /focus 命令")
