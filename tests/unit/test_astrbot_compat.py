"""AstrBot 兼容层单元测试 (F1, ARCHITECTURE.md 3.8)。"""

from __future__ import annotations

import pytest

from isac.plugin.compatibility.astrbot.context import ContextAdapter
from isac.plugin.compatibility.astrbot.star import filter
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
