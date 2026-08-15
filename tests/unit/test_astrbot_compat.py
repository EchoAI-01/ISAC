"""AstrBot 兼容层单元测试 (F1, ARCHITECTURE.md 3.8)。"""

from __future__ import annotations

import pytest

from isac.plugin.compatibility.astrbot.adapter import AstrBotStarAdapter
from isac.plugin.compatibility.astrbot.context import ContextAdapter
from isac.plugin.compatibility.astrbot.star import Star, filter
from isac.plugin.compatibility.astrbot.tools import bridge_function_tool


class TestFunctionToolAdapter:
    @pytest.mark.asyncio
    async def test_async_function_bridges_to_tool(self):
        async def my_tool(ctx, args):  # noqa: ANN001
            return f"hello {args.get('name', 'world')}"

        tool = bridge_function_tool("my_tool", "测试工具", my_tool)
        assert tool.name == "my_tool"
        assert tool.description == "测试工具"

        from isac.agent.tools.base import ToolContext
        from isac.core.types import AgentContext
        from isac.gateway.models import Session

        ctx = ToolContext(
            args={"name": "ISAC"},
            agent_context=AgentContext(
                session=Session(session_id="s1", user_id="u1", platform="qq"),
                user_profile=None,
                current_message=object(),
            ),
            services={},
        )
        result = await tool.execute(ctx)
        assert result.is_error is False
        assert result.content == "hello ISAC"

    @pytest.mark.asyncio
    async def test_sync_function_bridges_to_tool(self):
        def sync_tool(ctx, args):  # noqa: ANN001
            return f"sync {args.get('x')}"

        tool = bridge_function_tool("sync_tool", "同步工具", sync_tool)
        from isac.agent.tools.base import ToolContext
        from isac.core.types import AgentContext
        from isac.gateway.models import Session

        ctx = ToolContext(
            args={"x": 42},
            agent_context=AgentContext(
                session=Session(session_id="s1", user_id="u1", platform="qq"),
                user_profile=None,
                current_message=object(),
            ),
            services={},
        )
        result = await tool.execute(ctx)
        assert result.is_error is False
        assert result.content == "sync 42"

    @pytest.mark.asyncio
    async def test_exception_returns_error_result(self):
        async def bad_tool(ctx, args):  # noqa: ANN001
            raise ValueError("boom")

        tool = bridge_function_tool("bad_tool", "", bad_tool)
        from isac.agent.tools.base import ToolContext
        from isac.core.types import AgentContext
        from isac.gateway.models import Session

        ctx = ToolContext(
            args={},
            agent_context=AgentContext(
                session=Session(session_id="s1", user_id="u1", platform="qq"),
                user_profile=None,
                current_message=object(),
            ),
            services={},
        )
        result = await tool.execute(ctx)
        assert result.is_error is True
        assert "boom" in result.content


class TestStarAndFilter:
    def test_llm_tool_decorator_marks_function(self):
        @filter.llm_tool(name="custom_name", description="测试")
        def my_method(self, ctx, args):  # noqa: ANN001
            return ""

        assert my_method._isac_llm_tool == ("custom_name", "测试")

    def test_llm_tool_decorator_uses_func_name_when_no_name(self):
        @filter.llm_tool()
        def another_tool(self, ctx, args):  # noqa: ANN001
            """docstring"""
            return ""

        assert another_tool._isac_llm_tool == ("another_tool", "docstring")

    def test_on_message_decorator_marks_hook(self):
        @filter.on_message()
        def on_msg(self, ctx):  # noqa: ANN001
            return None

        assert on_msg._isac_event == "on_message"


class TestContextAdapter:
    def test_get_provider_without_service_returns_none(self):
        adapter = ContextAdapter({})
        assert adapter.get_provider() is None

    def test_get_platform_without_service_returns_none(self):
        adapter = ContextAdapter({})
        assert adapter.get_platform("qq") is None

    @pytest.mark.asyncio
    async def test_send_message_without_channel_raises(self):
        adapter = ContextAdapter({})
        with pytest.raises(RuntimeError, match="channel_registry"):
            await adapter.send_message("hello", "qq")


class _AstrBotFakeToolRegistry:
    """记录 register 调用 (仿 test_maibot_compat._FakeToolRegistry)。"""

    def __init__(self) -> None:
        self.registered: list = []

    def register(self, tool) -> None:  # noqa: ANN001
        self.registered.append(tool)


class _MyStarPlugin(Star):
    @filter.llm_tool(name="star_greet", description="打招呼")
    async def greet(self, ctx, args):  # noqa: ANN001
        return f"hello {args.get('name', 'world')}"

    @filter.llm_tool(name="star_sync")
    def sync_tool(self, ctx, args):  # noqa: ANN001
        return f"sync {args.get('x')}"

    @filter.on_message()
    async def on_msg(self, ctx):  # noqa: ANN001
        return None


class TestAstrBotStarAdapter:
    """R3: AstrBotStarAdapter 批量扫描 @filter.llm_tool/@filter.on_* 装饰器标记
    并桥接为 ISAC Tool (对标 MaiBotPluginAdapter)。此前只有单函数桥接原语,
    loader 加载 AstrBot 插件后 @filter.llm_tool 标记的 handler 是死代码。"""

    def test_scan_finds_decorated_tools_and_hooks(self):
        plugin = _MyStarPlugin(context=None)
        adapter = AstrBotStarAdapter(plugin)
        assert {t[0] for t in adapter.tools} == {"star_greet", "star_sync"}
        assert {h[0] for h in adapter.hooks} == {"on_message"}

    @pytest.mark.asyncio
    async def test_adapt_registers_tools_to_registry(self):
        plugin = _MyStarPlugin(context=None)
        adapter = AstrBotStarAdapter(plugin)
        tools_reg = _AstrBotFakeToolRegistry()
        result = await adapter.adapt(tools_reg)
        assert set(result["tools"]) == {"star_greet", "star_sync"}
        # hooks 本轮只收集不桥接 (签名适配留后续), 记录待处理清单
        assert result["hooks"] == ["on_message"]
        assert len(tools_reg.registered) == 2
        assert {t.name for t in tools_reg.registered} == {"star_greet", "star_sync"}

    @pytest.mark.asyncio
    async def test_adapt_without_registry_skips_register(self):
        plugin = _MyStarPlugin(context=None)
        adapter = AstrBotStarAdapter(plugin)
        # 不传 registry 时不报错, 只扫描; result["tools"] 是注册清单 (空, 因无 registry)
        result = await adapter.adapt(None)
        assert result["tools"] == []
        assert {t[0] for t in adapter.tools} == {"star_greet", "star_sync"}
