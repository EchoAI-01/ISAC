"""CommandRegistry: 命令注册与执行 (SPECIFICATION.md 2.11)。"""

from __future__ import annotations

from collections.abc import Callable

from isac.channel.model import ISACMessage
from isac.commands.base import Command
from isac.core.types import AgentContext
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 判断命令在某 Agent/平台是否启用的回调 (由 runtime 注入启用矩阵)
EnableChecker = Callable[[str, str, str], bool]  # (name, agent_id, platform) -> bool


class CommandRegistry:
    """命令注册表。"""

    def __init__(self, enable_checker: EnableChecker | None = None):
        self._commands: dict[str, Command] = {}
        self._enable_checker = enable_checker

    def register(self, command: Command) -> None:
        self._commands[command.name] = command

    def get(self, name: str) -> Command | None:
        return self._commands.get(name)

    def is_enabled(self, name: str, agent_id: str, platform: str) -> bool:
        if self._enable_checker is None:
            return True
        return self._enable_checker(name, agent_id, platform)

    async def try_execute(self, message: ISACMessage, context: AgentContext) -> str | None:
        """消息以 '/' 开头时尝试执行命令；未命中/已禁用返回 None。"""
        content = message.content.strip()
        if not content.startswith("/"):
            return None
        name, _, args = content[1:].partition(" ")
        command = self._commands.get(name)
        if command is None:
            return None
        agent_id = context.session.agent_id if context.session else ""
        if not self.is_enabled(name, agent_id, message.platform):
            logger.info("命令已禁用，忽略", command=name, agent_id=agent_id)
            return "该命令当前不可用"
        try:
            return await command.execute(message, args.strip(), context)
        except Exception as exc:
            logger.error("命令执行失败", command=name, error=str(exc), exc_info=True)
            return f"命令执行失败: {exc}"
