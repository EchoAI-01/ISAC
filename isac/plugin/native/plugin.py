"""ISACPlugin 基类与插件上下文 (ARCHITECTURE.md 3.8 原生 SDK v2)。

原生 SDK 超越兼容层的能力:
- Hooks / Injectors / Tools (基础能力)
- Commands (用户斜杠命令, 按 Agent/Channel 启停)
- Inter-Agent Hooks (on_inter_agent_message 等)
- Admin Routes (预留: 插件向 Admin API 注册管理端点)
- 自定义扩展点 (预留: Memory Backend / Provider / Router Hook)
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.agent.hooks import AgentHooks
    from isac.agent.injector import PromptInjector
    from isac.agent.tools.base import Tool
    from isac.commands.base import Command
    from isac.gateway.event_bus import EventBus
    from isac.router.router import MessageRouter


@dataclass
class PluginContext:
    """插件上下文: 插件与 ISAC 交互的唯一入口 (组装时注入)。"""

    agent_hooks: AgentHooks
    event_bus: EventBus
    router: MessageRouter | None = None
    services: dict[str, Any] = field(default_factory=dict)

    # ── 基础能力 ────────────────────────────────────────────

    def register_tool(self, tool: Tool) -> None:
        raise NotImplementedError("TODO(Day 54): 插件工具注册")

    def register_injector(self, injector: PromptInjector) -> None:
        raise NotImplementedError("TODO(Day 54): 插件注入器注册")

    def register_command(self, command: Command) -> None:
        raise NotImplementedError("TODO(Day 54): 插件命令注册")

    # ── 独有能力 (Native SDK v2) ────────────────────────────

    def register_inter_agent_hook(self, fn: Any) -> None:
        """注册互联钩子 (如 on_inter_agent_message)。"""
        raise NotImplementedError("TODO(Day 54): 互联钩子注册")

    def register_admin_route(self, path: str, handler: Any) -> None:
        """预留: 向 Admin API 注册管理端点 (控制面扩展)。"""
        raise NotImplementedError("TODO(预留): Admin Routes")

    def register_router_hook(self, fn: Any) -> None:
        """预留: 自定义路由函数 (MessageRouter 优先级 0)。"""
        if self.router is None:
            raise RuntimeError("Router 未注入")
        self.router.register_router_hook(fn)


class ISACPlugin(ABC):
    """ISAC 原生插件基类。

    插件目录结构:
        plugins/my_plugin/
        ├── manifest.jsonc   # Plugin Manifest (SPECIFICATION.md 2.6)
        └── plugin.py        # 入口, 含一个 ISACPlugin 子类
    """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    async def on_load(self, context: PluginContext) -> None:
        """插件加载时调用: 在此注册 hooks/tools/commands/injectors。"""

    async def on_unload(self) -> None:
        """插件卸载时调用: 清理资源。"""
