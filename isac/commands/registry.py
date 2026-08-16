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
        # N5b 批次C C2: 来源追踪 (name → "builtin" 或插件名), 供热重载按来源 deregister。
        self._source: dict[str, str] = {}
        # on_load 期间设置的默认来源 (激活模块 set_current_source(plugin_name))。
        self._current_source: str | None = None
        self._enable_checker = enable_checker

    def register(self, command: Command, *, source: str | None = None) -> None:
        effective_source = source or self._current_source or "builtin"
        self._commands[command.name] = command
        self._source[command.name] = effective_source

    def set_current_source(self, source: str | None) -> None:
        """设置后续 register() 的默认来源 (on_load 期间设为插件名, 结束后置 None)。"""
        self._current_source = source

    def deregister_by_source(self, source: str) -> list[str]:
        """移除指定来源的全部命令, 返回被移除的命令名列表 (C2 热重载同步)。"""
        removed = [n for n, s in self._source.items() if s == source]
        for n in removed:
            self._commands.pop(n, None)
            self._source.pop(n, None)
        return removed

    def get_by_source(self, source: str) -> list[Command]:
        """返回指定来源的全部命令 (C2 热重载同步)。"""
        return [self._commands[n] for n, s in self._source.items() if s == source and n in self._commands]

    def deregister_plugin_sourced(self) -> list[str]:
        """移除全部插件来源命令 (source != "builtin"), 返回被移除的命令名列表 (C2)。"""
        removed = [n for n, s in self._source.items() if s != "builtin"]
        for n in removed:
            self._commands.pop(n, None)
            self._source.pop(n, None)
        return removed

    def items_with_source(self) -> list[tuple[Command, str]]:
        """返回 (command, source) 列表 (C2: 全量同步模式用)。"""
        return [(cmd, self._source.get(name, "builtin")) for name, cmd in self._commands.items()]

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
