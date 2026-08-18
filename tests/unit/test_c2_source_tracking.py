"""N5b 批次C C2: 四类注册表来源追踪 + deregister_by_source 测试。

CommandRegistry/SystemPromptBuilder/AgentHooks/EventBus 此前 append-only 无来源
追踪, 插件 reload/uninstall 后旧命令/注入器/钩子/事件订阅残留。本轮加 _source 追踪
+ set_current_source + deregister_by_source (+ get_by_source / deregister_plugin_sourced
/ items_with_source), 实现按来源精确清理。
"""

from __future__ import annotations

from types import SimpleNamespace

from isac.agent.hooks import AgentHooks
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.commands.registry import CommandRegistry
from isac.core.events import AgentHookPoint, EventType
from isac.gateway.event_bus import EventBus


def _cmd(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _inj(key: str) -> SimpleNamespace:
    """最小 PromptInjector 替身 (deregister 不调 build, 只需可注册)。"""
    return SimpleNamespace(key=key, priority=0, enabled=True)


class TestCommandRegistrySourceTracking:
    def test_register_with_source_marks_source(self) -> None:
        reg = CommandRegistry()
        reg.register(_cmd("c1"), source="pluginA")
        assert reg.get("c1") is not None
        # source 经 get_by_source 可查
        assert len(reg.get_by_source("pluginA")) == 1
        assert len(reg.get_by_source("pluginB")) == 0

    def test_set_current_source_marks_subsequent_registers(self) -> None:
        reg = CommandRegistry()
        reg.set_current_source("pluginA")
        reg.register(_cmd("c1"))  # 无显式 source, 取 _current_source
        reg.set_current_source(None)
        assert len(reg.get_by_source("pluginA")) == 1
        # builtin 的命令不受影响
        reg.register(_cmd("c_builtin"), source="builtin")
        assert len(reg.get_by_source("pluginA")) == 1

    def test_deregister_by_source_removes_only_that_source(self) -> None:
        reg = CommandRegistry()
        reg.register(_cmd("a1"), source="pluginA")
        reg.register(_cmd("a2"), source="pluginA")
        reg.register(_cmd("b1"), source="pluginB")
        removed = reg.deregister_by_source("pluginA")
        assert sorted(removed) == ["a1", "a2"]
        assert reg.get("a1") is None and reg.get("a2") is None
        assert reg.get("b1") is not None  # 其他插件不受影响

    def test_deregister_plugin_sourced_keeps_builtin(self) -> None:
        reg = CommandRegistry()
        reg.register(_cmd("b"), source="builtin")
        reg.register(_cmd("p"), source="pluginA")
        removed = reg.deregister_plugin_sourced()
        assert removed == ["p"]
        assert reg.get("b") is not None
        assert reg.get("p") is None

    def test_items_with_source_pairs(self) -> None:
        reg = CommandRegistry()
        reg.register(_cmd("b"), source="builtin")
        reg.register(_cmd("p"), source="pluginA")
        pairs = dict((c.name, src) for c, src in reg.items_with_source())
        assert pairs == {"b": "builtin", "p": "pluginA"}


class TestSystemPromptBuilderSourceTracking:
    def test_deregister_by_source_removes_injectors(self) -> None:
        pb = SystemPromptBuilder()
        pb.register(_inj("a1"), source="pluginA")
        pb.register(_inj("a2"), source="pluginA")
        pb.register(_inj("b1"), source="pluginB")
        removed = pb.deregister_by_source("pluginA")
        assert removed == 2
        assert len(pb.get_by_source("pluginA")) == 0
        assert len(pb.get_by_source("pluginB")) == 1

    def test_deregister_plugin_sourced_keeps_builtin(self) -> None:
        pb = SystemPromptBuilder()
        pb.register(_inj("b"), source="builtin")
        pb.register(_inj("p"), source="pluginA")
        removed = pb.deregister_plugin_sourced()
        assert removed == 1
        assert len(pb.get_by_source("builtin")) == 1

    def test_set_current_source_marks_subsequent_registers(self) -> None:
        pb = SystemPromptBuilder()
        pb.set_current_source("pluginA")
        pb.register(_inj("a1"))
        pb.set_current_source(None)
        assert len(pb.get_by_source("pluginA")) == 1


class TestAgentHooksSourceTracking:
    def test_deregister_by_source_removes_hooks(self) -> None:
        hooks = AgentHooks()
        hooks.register(AgentHookPoint.PRE_LLM, lambda ctx: None, source="pluginA")
        hooks.register(AgentHookPoint.PRE_LLM, lambda ctx: None, source="pluginA")
        hooks.register(AgentHookPoint.PRE_LLM, lambda ctx: None, source="pluginB")
        removed = hooks.deregister_by_source("pluginA")
        assert removed == 2
        assert len(hooks.get_hooks(AgentHookPoint.PRE_LLM)) == 1  # 只剩 pluginB 的

    def test_set_current_source_marks_subsequent_registers(self) -> None:
        hooks = AgentHooks()
        hooks.set_current_source("pluginA")
        hooks.register(AgentHookPoint.PRE_LLM, lambda ctx: None)
        hooks.set_current_source(None)
        # deregister pluginA 应移除该钩子
        assert hooks.deregister_by_source("pluginA") == 1


class TestEventBusSourceTracking:
    def test_deregister_by_source_removes_handlers(self) -> None:
        eb = EventBus()
        eb.on_intercept(EventType.ON_MESSAGE, lambda p: p, source="pluginA")
        eb.on_async(EventType.ON_MESSAGE, lambda p: None, source="pluginA")
        eb.on_async(EventType.ON_MESSAGE, lambda p: None, source="pluginB")
        removed = eb.deregister_by_source("pluginA")
        assert removed == 2
        # pluginB 的 async 还在
        assert len(eb._async.get(EventType.ON_MESSAGE, [])) == 1  # noqa: SLF001

    def test_set_current_source_marks_subsequent_registers(self) -> None:
        eb = EventBus()
        eb.set_current_source("pluginA")
        eb.on_async(EventType.ON_MESSAGE, lambda p: None)
        eb.set_current_source(None)
        assert eb.deregister_by_source("pluginA") == 1
