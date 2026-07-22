"""MaiBot Plugin 基类映射 (ARCHITECTURE.md 3.8 兼容表)。

将 MaiBot Plugin 基类包装为 ISACPlugin; MaiBot 插件配置 → Plugin Manifest config_schema。
扫描 MaiBot 插件类上的 @register_action / @register_command 装饰器, 转换为 ISAC Tool / Command。
"""

from __future__ import annotations

from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class MaiBotPlugin:
    """兼容 MaiBot Plugin 基类 (插件作者继承此类)。

    MaiBot 插件约定:
    - __init__(self, config): 接收配置 dict
    - async on_load(self): 加载时调用
    - @register_action(name, description): 装饰方法注册为 Action (→ ISAC Tool)
    - @register_command(name): 装饰方法注册为 Command
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def on_load(self) -> None:
        """插件加载时调用 (子类覆盖)。"""


class MaiBotPluginAdapter:
    """MaiBot Plugin → ISAC 包装器。

    扫描插件类上的装饰器标记:
    - _maibot_action: (name, description, func) → bridge_action
    - _maibot_command: (name, func) → bridge_command

    加载时把适配结果注册到 ISAC ToolRegistry / CommandRegistry。
    """

    def __init__(self, maibot_plugin: Any):
        self._plugin = maibot_plugin
        self._actions: list[tuple[str, str, Any]] = []
        self._commands: list[tuple[str, Any]] = []
        self._scan_decorators()

    def _scan_decorators(self) -> None:
        """扫描插件实例上的方法, 收集装饰器标记。"""
        for attr_name in dir(self._plugin):
            if attr_name.startswith("_"):
                continue
            try:
                method = getattr(self._plugin, attr_name)
            except Exception:  # noqa: BLE001 防御
                continue
            if not callable(method):
                continue
            action = getattr(method, "_maibot_action", None)
            command = getattr(method, "_maibot_command", None)
            if action:
                self._actions.append((action[0], action[1], method))
            if command:
                self._commands.append((command[0], method))

    @property
    def actions(self) -> list[tuple[str, str, Any]]:
        return list(self._actions)

    @property
    def commands(self) -> list[tuple[str, Any]]:
        return list(self._commands)

    async def adapt(
        self,
        tools_registry: Any | None = None,
        commands_registry: Any | None = None,
    ) -> dict[str, Any]:
        """把 Action/Command 注册到 ISAC Registry, 返回注册清单。"""
        from isac.plugin.compatibility.maibot.actions import bridge_action
        from isac.plugin.compatibility.maibot.commands import bridge_command

        registered_tools: list[str] = []
        registered_commands: list[str] = []

        for name, description, func in self._actions:
            if tools_registry is None:
                continue
            tool = bridge_action(name, description, func)
            tools_registry.register(tool)
            registered_tools.append(name)

        for name, func in self._commands:
            if commands_registry is None:
                continue
            command = bridge_command(name, func)
            commands_registry.register(command)
            registered_commands.append(name)

        logger.info(
            "MaiBot 插件适配完成",
            plugin=type(self._plugin).__name__,
            tools=registered_tools,
            commands=registered_commands,
        )
        return {"tools": registered_tools, "commands": registered_commands}


# ── MaiBot 装饰器 (供插件代码使用) ─────────────────────────────


def register_action(name: str, description: str = "") -> Any:
    """MaiBot @register_action → 标记方法为 Action (→ ISAC Tool)。"""

    def decorator(func: Any) -> Any:
        func._maibot_action = (name, description or func.__doc__ or "")  # type: ignore[attr-defined]
        return func

    return decorator


def register_command(name: str) -> Any:
    """MaiBot @register_command → 标记方法为 Command。"""

    def decorator(func: Any) -> Any:
        func._maibot_command = (name,)  # type: ignore[attr-defined]
        return func

    return decorator
