"""T6 activation 模块测试: activate_plugin + sync_plugin_tools_to_agents。

验证热重载核心路径: 激活后工具写入共享表并带 source 追踪; sync 把共享表变更
同步到运行中 Agent 的 per-Agent registry (注入新工具 + 移除旧工具)。
"""

from __future__ import annotations

from typing import Any

import pytest

from isac.agent.tools.base import Tool, ToolContext, ToolResult
from isac.agent.tools.registry import ToolRegistry
from isac.plugin.runtime.activation import (
    activate_plugin,
    ensure_shared_registries,
    sync_plugin_tools_to_agents,
)


class _NamedTool(Tool):
    def __init__(self, tool_name: str) -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "test"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content="ok")


class _FakeAgent:
    def __init__(self, agent_id: str = "a1") -> None:
        self.agent_id = agent_id
        self.status = "running"
        self.tools = ToolRegistry()
        self.commands: Any = None
        self.prompt_builder: Any = None


class _FakeAgentManager:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    async def list(self) -> list[_FakeAgent]:
        return self._agents


class _FakeLoaded:
    def __init__(self, instance: Any = None) -> None:
        self.instance = instance

    def is_native(self) -> bool:
        return True

    def is_astrbot(self) -> bool:
        return False

    def is_maibot(self) -> bool:
        return False


class _FakeNativePlugin:
    def __init__(self) -> None:
        self.on_load_called = False

    async def on_load(self, context: Any) -> None:
        self.on_load_called = True
        context.register_tool(_NamedTool("native_tool"))


class _FakePluginManager:
    def __init__(self, loaded: dict[str, _FakeLoaded]) -> None:
        self._loaded = loaded

    def get(self, name: str) -> _FakeLoaded | None:
        return self._loaded.get(name)

    async def call_on_load_one(self, name: str, context: Any) -> str:
        loaded = self._loaded.get(name)
        if loaded and loaded.instance:
            await loaded.instance.on_load(context)
            return "ok"
        return "skipped"

    async def adapt_one(self, name: str, shared_tools: Any, shared_commands: Any) -> str:
        return "skipped"


@pytest.mark.asyncio
async def test_ensure_shared_registries_idempotent() -> None:
    services: dict[str, Any] = {}
    t1, _c1, _p1, _h1 = await ensure_shared_registries(services)
    t2, _c2, _p2, _h2 = await ensure_shared_registries(services)
    assert t1 is t2
    assert services["plugin_tools"] is t1


@pytest.mark.asyncio
async def test_activate_plugin_native_registers_with_source() -> None:
    plugin = _FakeNativePlugin()
    pm = _FakePluginManager({"p1": _FakeLoaded(instance=plugin)})
    services: dict[str, Any] = {}
    status = await activate_plugin(pm, "p1", services, event_bus=object())
    assert status == "ok"
    assert plugin.on_load_called
    shared_tools = services["plugin_tools"]
    assert shared_tools.get("native_tool") is not None
    assert shared_tools.source_of("native_tool") == "p1"


@pytest.mark.asyncio
async def test_activate_plugin_skips_without_event_bus() -> None:
    pm = _FakePluginManager({})
    status = await activate_plugin(pm, "p1", {}, event_bus=None)
    assert status == "skipped"


@pytest.mark.asyncio
async def test_sync_injects_to_running_agents() -> None:
    services: dict[str, Any] = {}
    shared_tools, _shared_commands, _shared_prompt, _hooks = await ensure_shared_registries(services)
    shared_tools.register(_NamedTool("t1"), source="p1")
    agent = _FakeAgent()
    mgr = _FakeAgentManager([agent])
    result = await sync_plugin_tools_to_agents(mgr, services, "p1")
    assert agent.tools.get("t1") is not None
    assert agent.tools.source_of("t1") == "p1"
    assert "a1" in result


@pytest.mark.asyncio
async def test_sync_removes_old_tools() -> None:
    services: dict[str, Any] = {}
    shared_tools, _shared_commands, _shared_prompt, _hooks = await ensure_shared_registries(services)
    agent = _FakeAgent()
    agent.tools.register(_NamedTool("old_t"), source="p1")  # 旧工具
    mgr = _FakeAgentManager([agent])
    # 共享表面前无 p1 工具 (模拟插件已 deregister)
    result = await sync_plugin_tools_to_agents(mgr, services, "p1")
    assert agent.tools.get("old_t") is None
    assert result["a1"] == ["old_t"]


@pytest.mark.asyncio
async def test_sync_skips_non_running() -> None:
    services: dict[str, Any] = {}
    shared_tools, _shared_commands, _shared_prompt, _hooks = await ensure_shared_registries(services)
    shared_tools.register(_NamedTool("t1"), source="p1")
    agent = _FakeAgent()
    agent.status = "stopped"
    mgr = _FakeAgentManager([agent])
    await sync_plugin_tools_to_agents(mgr, services, "p1")
    assert agent.tools.get("t1") is None
