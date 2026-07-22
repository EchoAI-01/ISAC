"""原生 SDK v2 (F3) 单元测试。"""

from __future__ import annotations

import pytest

from isac.agent.hooks import AgentHooks
from isac.agent.tools.base import Tool, ToolContext
from isac.agent.tools.registry import ToolRegistry
from isac.commands.base import Command
from isac.commands.registry import CommandRegistry
from isac.core.events import AgentHookPoint
from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext, ToolResult
from isac.gateway.event_bus import EventBus
from isac.plugin.native.plugin import ISACPlugin, make_plugin_context


class _DummyTool(Tool):
    @property
    def name(self) -> str:
        return "dummy_tool"

    @property
    def description(self) -> str:
        return "测试工具"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content="ok")


class _DummyCommand(Command):
    @property
    def name(self) -> str:
        return "dummy_cmd"

    async def execute(self, message, args, context) -> str:  # noqa: ANN001
        return "cmd_ok"


class _DummyInjector(PromptInjector):
    @property
    def key(self) -> str:
        return "dummy_injector"

    async def build(self, context: InjectionContext) -> str:
        return ""


class _MyPlugin(ISACPlugin):
    async def on_load(self, context) -> None:  # noqa: ANN001
        context.register_tool(_DummyTool())
        context.register_command(_DummyCommand())
        context.register_injector(_DummyInjector())


class TestPluginContext:
    def test_register_tool_requires_tools_registry(self):
        context = make_plugin_context(
            agent_hooks=AgentHooks(), event_bus=EventBus(), services={}
        )
        with pytest.raises(RuntimeError, match="ToolRegistry"):
            context.register_tool(_DummyTool())

    def test_register_command_requires_commands_registry(self):
        context = make_plugin_context(
            agent_hooks=AgentHooks(), event_bus=EventBus(), services={}
        )
        with pytest.raises(RuntimeError, match="CommandRegistry"):
            context.register_command(_DummyCommand())

    def test_register_injector_requires_prompt_builder(self):
        from isac.agent.prompt_builder import SystemPromptBuilder

        context = make_plugin_context(
            agent_hooks=AgentHooks(),
            event_bus=EventBus(),
            services={},
            prompt_builder=SystemPromptBuilder(),
        )
        # 不抛异常即成功
        context.register_injector(_DummyInjector())


class TestPluginLifecycle:
    @pytest.mark.asyncio
    async def test_plugin_on_load_registers_resources(self):
        from isac.agent.prompt_builder import SystemPromptBuilder

        tools = ToolRegistry()
        commands = CommandRegistry()
        prompt_builder = SystemPromptBuilder()
        context = make_plugin_context(
            agent_hooks=AgentHooks(),
            event_bus=EventBus(),
            services={},
            tools=tools,
            commands=commands,
            prompt_builder=prompt_builder,
        )
        plugin = _MyPlugin()
        await plugin.on_load(context)

        assert tools.get("dummy_tool") is not None
        assert commands.get("dummy_cmd") is not None
        assert any(injector.key == "dummy_injector" for injector in prompt_builder._injectors)

    @pytest.mark.asyncio
    async def test_plugin_default_on_load_no_op(self):
        # 空实现不应抛异常
        plugin = ISACPlugin()
        context = make_plugin_context(
            agent_hooks=AgentHooks(), event_bus=EventBus(), services={}
        )
        await plugin.on_load(context)

    @pytest.mark.asyncio
    async def test_plugin_default_on_unload_no_op(self):
        plugin = ISACPlugin()
        await plugin.on_unload()

    def test_plugin_name_defaults_to_class_name(self):
        class _NamedPlugin(ISACPlugin):
            pass

        assert _NamedPlugin().name == "_NamedPlugin"


class TestEventBusSubscription:
    @pytest.mark.asyncio
    async def test_on_event_async_registers_handler(self):
        event_bus = EventBus()
        context = make_plugin_context(
            agent_hooks=AgentHooks(), event_bus=event_bus, services={}
        )
        called: list = []

        async def handler(payload):  # noqa: ANN001
            called.append(payload)

        context.on_event_async(AgentHookPoint.PRE_LLM, handler)
        # 直接触发 async 看是否注册到 _async dict
        assert AgentHookPoint.PRE_LLM in event_bus._async


class TestAdminRouteReservation:
    def test_register_admin_route_collects_to_services(self):
        context = make_plugin_context(
            agent_hooks=AgentHooks(), event_bus=EventBus(), services={}
        )
        context.register_admin_route("/foo", lambda: None)
        context.register_admin_route("/bar", lambda: None)
        routes = context.services.get("admin_routes", [])
        assert len(routes) == 2
        assert routes[0][0] == "/foo"
