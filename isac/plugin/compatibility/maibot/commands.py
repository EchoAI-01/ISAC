"""MaiBot Command 映射 (ARCHITECTURE.md 3.8 兼容表)。

将 MaiBot Command (命令) 桥接为 ISAC Command。MaiBot Command 签名:
    async def my_command(self, message, args) -> str: ...
ISAC Command 调用约定: (message, args, context)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from isac.commands.base import Command

if TYPE_CHECKING:
    from isac.channel.model import ISACMessage
    from isac.core.types import AgentContext


class MaiBotCommandAdapter(Command):
    """MaiBot Command → ISAC Command 桥接器。"""

    def __init__(self, name: str, func: Any):
        self._name = name
        self._func = func

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return getattr(self._func, "__doc__", "") or f"MaiBot 命令 {self._name}"

    async def execute(self, message: ISACMessage, args: str, context: AgentContext) -> str:
        """调用原 MaiBot Command。"""
        del context  # MaiBot Command 不使用 context
        import inspect

        is_async = inspect.iscoroutinefunction(self._func)
        try:
            if is_async:
                raw = await self._func(message, args)
            else:
                raw = self._func(message, args)
        except Exception as exc:
            return f"Command {self._name} 执行失败: {exc}"
        if raw is None:
            return ""
        return str(raw)


def bridge_command(name_or_command: Any, func: Any = None) -> Command:
    """将 MaiBot Command 桥接为 ISAC Command。

    两种用法:
    - bridge_command(name, func) 显式传 name 和函数
    - bridge_command(bound_method) 从装饰器标记读取 name
    """
    if callable(name_or_command) and func is None:
        func = name_or_command
        name = getattr(func, "_maibot_command", (func.__name__,))[0]
    elif isinstance(name_or_command, str) and func is not None:
        name = name_or_command
    else:
        raise ValueError("bridge_command 参数无效")
    return MaiBotCommandAdapter(name, func)
