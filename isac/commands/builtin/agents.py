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
        agent_manager = context.services.get("agent_manager")
        if agent_manager is None:
            return "Agent 管理器未注入, 无法列举。"
        instances = await agent_manager.list()
        if not instances:
            return "当前没有 Agent。"
        lines = ["当前 Agent 列表:"]
        for instance in instances:
            mark = "●" if instance.status == "running" else "○"
            lines.append(f"  {mark} {instance.agent_id}  [{instance.status}]  {instance.config.display_name}")
        return "\n".join(lines)
