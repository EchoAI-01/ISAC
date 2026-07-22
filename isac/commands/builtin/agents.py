"""/agents 命令: 列出当前运行的 Agent。"""

from __future__ import annotations

from isac.channel.model import ISACMessage
from isac.commands.base import Command
from isac.core.types import AgentContext


class AgentsCommand(Command):
    @property
    def name(self) -> str:
        return "agents"

    @property
    def description(self) -> str:
        return "列出当前所有 Agent 及其状态"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """经注入的 AgentManager.list() 生成清单。"""
        raise NotImplementedError("AgentsCommand.execute 尚未实现")
