"""ISACPlugin 基类与插件上下文 (ARCHITECTURE.md 3.8 原生 SDK v2)。

原生 SDK 超越兼容层的能力:
- Hooks / Injectors / Tools (基础能力)
- Commands (用户斜杠命令, 按 Agent/Channel 启停)
- Inter-Agent Hooks (on_inter_agent_message 等)
- Admin Routes (预留: 插件向 Admin API 注册管理端点)
- 自定义扩展点 (预留: Memory Backend / Provider / Router Hook)

PluginContext 持有 AgentHooks / EventBus / ToolRegistry / CommandRegistry / InterAgentBus
等引用, 通过 register_* 方法把插件的能力注册到 ISAC 运行时。
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.agent.hooks import AgentHooks
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.base import Tool
    from isac.agent.tools.registry import ToolRegistry
    from isac.commands.base import Command
    from isac.commands.registry import CommandRegistry
    from isac.core.injector import PromptInjector
    from isac.gateway.event_bus import EventBus
    from isac.router.router import MessageRouter
    from isac.runtime.bus import InterAgentBus


@dataclass
class PluginContext:
    """插件上下文: 插件与 ISAC 交互的唯一入口 (组装时注入)。"""

    agent_hooks: AgentHooks
    event_bus: EventBus
    router: MessageRouter | None = None
    services: dict[str, Any] = field(default_factory=dict)
    # 内部注入的 Registry 引用
    _tools: ToolRegistry | None = None
    _commands: CommandRegistry | None = None
    _prompt_builder: SystemPromptBuilder | None = None
    _inter_agent_bus: InterAgentBus | None = None

    # ── 基础能力 ────────────────────────────────────────────

    def register_tool(self, tool: Tool) -> None:
        """注册工具到 ToolRegistry (经 EnableMatrix 启用矩阵生效)。"""
        if self._tools is None:
            raise RuntimeError("未注入 ToolRegistry, 无法注册工具")
        self._tools.register(tool)

    def register_injector(self, injector: PromptInjector) -> None:
        """注册 Prompt 注入器到 SystemPromptBuilder。"""
        if self._prompt_builder is None:
            raise RuntimeError("未注入 SystemPromptBuilder, 无法注册注入器")
        self._prompt_builder.register(injector)

    def register_command(self, command: Command) -> None:
        """注册命令到 CommandRegistry (经 EnableMatrix commands_allow 生效)。"""
        if self._commands is None:
            raise RuntimeError("未注入 CommandRegistry, 无法注册命令")
        self._commands.register(command)

    # ── 独有能力 (Native SDK v2) ────────────────────────────

    def register_inter_agent_hook(self, fn: Any) -> None:
        """注册互联钩子 (如 on_inter_agent_message) 到 InterAgentBus。"""
        if self._inter_agent_bus is None:
            raise RuntimeError("未注入 InterAgentBus, 无法注册互联钩子")
        # InterAgentBus 待扩展 hooks 字段, 这里通过 setattr 兜底 (向前兼容)
        hooks = getattr(self._inter_agent_bus, "_inter_agent_hooks", None)
        if hooks is None:
            hooks = []
            setattr(self._inter_agent_bus, "_inter_agent_hooks", hooks)
        hooks.append(fn)

    def register_admin_route(self, path: str, handler: Any) -> None:
        """预留: 向 Admin API 注册管理端点 (控制面扩展)。

        待 G1 Admin API 完成后, 此方法会把 (path, handler) 注册到 FastAPI app。
        当前记录到 services["admin_routes"] 待控制面启动时消费。
        """
        routes = self.services.setdefault("admin_routes", [])
        routes.append((path, handler))

    def register_router_hook(self, fn: Any) -> None:
        """预留: 自定义路由函数 (MessageRouter 优先级 0)。"""
        if self.router is None:
            raise RuntimeError("Router 未注入")
        self.router.register_router_hook(fn)

    # ── EventBus 订阅 ───────────────────────────────────────

    def on_event_intercept(self, event_type: Any, handler: Any, priority: int = 0) -> None:
        """订阅 EventBus Intercept 事件 (可拦截主流程)。"""
        self.event_bus.on_intercept(event_type, handler, priority=priority)

    def on_event_async(self, event_type: Any, handler: Any) -> None:
        """订阅 EventBus Async 事件 (不阻塞主流程, 异常隔离)。"""
        self.event_bus.on_async(event_type, handler)


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


def make_plugin_context(
    *,
    agent_hooks: AgentHooks,
    event_bus: EventBus,
    services: dict[str, Any],
    tools: ToolRegistry | None = None,
    commands: CommandRegistry | None = None,
    prompt_builder: SystemPromptBuilder | None = None,
    inter_agent_bus: InterAgentBus | None = None,
    router: MessageRouter | None = None,
) -> PluginContext:
    """工厂: 用运行时各 Registry 构造 PluginContext (供 PluginManager 加载时使用)。"""
    return PluginContext(
        agent_hooks=agent_hooks,
        event_bus=event_bus,
        router=router,
        services=services,
        _tools=tools,
        _commands=commands,
        _prompt_builder=prompt_builder,
        _inter_agent_bus=inter_agent_bus,
    )
