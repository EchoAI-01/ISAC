"""MaiBot 兼容层单元测试 (F2, ARCHITECTURE.md 3.8)。"""

from __future__ import annotations

import pytest

from isac.agent.tools.base import ToolContext
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.plugin.compatibility.maibot.actions import bridge_action
from isac.plugin.compatibility.maibot.commands import bridge_command
from isac.plugin.compatibility.maibot.plugin import (
    MaiBotPlugin,
    MaiBotPluginAdapter,
    register_action,
    register_command,
)


def _make_tool_context(args: dict | None = None) -> ToolContext:
    return ToolContext(
        args=args or {},
        agent_context=AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=None,
            current_message=object(),
        ),
        services={},
    )


class _FakeToolRegistry:
    def __init__(self) -> None:
        self.registered: list = []

    def register(self, tool) -> None:
        self.registered.append(tool)


class _FakeCmdRegistry:
    def __init__(self) -> None:
        self.registered: list = []

    def register(self, cmd) -> None:
        self.registered.append(cmd)


class _MyMaiBotPlugin(MaiBotPlugin):
    @register_action(name="greet", description="打招呼")
    async def greet(self, args):  # noqa: ANN001
        return f"hello {args.get('name', 'world')}"

    @register_action(name="sync_act")
    def sync_act(self, args):  # noqa: ANN001
        return f"sync {args.get('x')}"

    @register_command(name="hello")
    async def hello_cmd(self, message, args):  # noqa: ANN001
        return f"hello cmd {args}"

    @register_action(name="bad_act")
    async def bad_act(self, args):  # noqa: ANN001
        raise RuntimeError("boom")


class TestMaiBotPluginAdapter:
    def test_scan_finds_all_decorated_methods(self):
        plugin = _MyMaiBotPlugin({})
        adapter = MaiBotPluginAdapter(plugin)
        assert {a[0] for a in adapter.actions} == {"greet", "sync_act", "bad_act"}
        assert {c[0] for c in adapter.commands} == {"hello"}

    @pytest.mark.asyncio
    async def test_adapt_registers_to_registries(self):
        plugin = _MyMaiBotPlugin({})
        adapter = MaiBotPluginAdapter(plugin)
        tools_reg = _FakeToolRegistry()
        cmds_reg = _FakeCmdRegistry()
        result = await adapter.adapt(tools_reg, cmds_reg)
        assert set(result["tools"]) == {"greet", "sync_act", "bad_act"}
        assert result["commands"] == ["hello"]
        assert len(tools_reg.registered) == 3
        assert len(cmds_reg.registered) == 1


class TestActionBridge:
    @pytest.mark.asyncio
    async def test_async_action_executes(self):
        plugin = _MyMaiBotPlugin({})
        tool = bridge_action("greet", "打招呼", plugin.greet)
        result = await tool.execute(_make_tool_context({"name": "ISAC"}))
        assert result.is_error is False
        assert result.content == "hello ISAC"

    @pytest.mark.asyncio
    async def test_sync_action_executes(self):
        plugin = _MyMaiBotPlugin({})
        tool = bridge_action("sync_act", "", plugin.sync_act)
        result = await tool.execute(_make_tool_context({"x": 42}))
        assert result.is_error is False
        assert result.content == "sync 42"

    @pytest.mark.asyncio
    async def test_action_exception_isolated(self):
        plugin = _MyMaiBotPlugin({})
        tool = bridge_action("bad_act", "", plugin.bad_act)
        result = await tool.execute(_make_tool_context({}))
        assert result.is_error is True
        assert "boom" in result.content


class TestCommandBridge:
    @pytest.mark.asyncio
    async def test_command_executes(self):
        plugin = _MyMaiBotPlugin({})
        cmd = bridge_command("hello", plugin.hello_cmd)
        from isac.channel.model import ISACMessage

        msg = ISACMessage(
            msg_id="m1",
            platform="qq",
            timestamp=0,
            user_id="u1",
            user_name="",
            content="/hello world",
        )
        from isac.core.types import AgentContext

        ctx = AgentContext(
            session=Session(session_id="s1", user_id="u1", platform="qq"),
            user_profile=None,
            current_message=msg,
        )
        result = await cmd.execute(msg, "world", ctx)
        assert result == "hello cmd world"
