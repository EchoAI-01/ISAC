"""/mute /unmute 命令: 会话静音开关。"""

from __future__ import annotations

from isac.channel.model import ISACMessage
from isac.commands.base import Command
from isac.core.types import AgentContext


class MuteCommand(Command):
    @property
    def name(self) -> str:
        return "mute"

    @property
    def description(self) -> str:
        return "在当前会话静音 (Bot 不再主动回复)"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """设置会话级静音标志 (门控强制 WAIT)。"""
        raise NotImplementedError("MuteCommand.execute 尚未实现")


class UnmuteCommand(Command):
    @property
    def name(self) -> str:
        return "unmute"

    @property
    def description(self) -> str:
        return "取消当前会话静音"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """清除会话级静音标志。"""
        raise NotImplementedError("UnmuteCommand.execute 尚未实现")
