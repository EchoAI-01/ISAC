"""ToolRegistry 单元测试。"""

from __future__ import annotations

import pytest

from isac.agent.tools.base import Tool, ToolContext, ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.core.types import AgentContext, ToolCall, ToolResult


class ServiceEchoTool(Tool):
    @property
    def name(self) -> str:
        return "service_echo"

    @property
    def description(self) -> str:
        return "回显注入服务"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content=context.services["memory"])


class FlagTool(Tool):
    def __init__(self) -> None:
        self.executed = False

    @property
    def name(self) -> str:
        return "flag"

    @property
    def description(self) -> str:
        return "标记是否执行"

    async def execute(self, context: ToolContext) -> ToolResult:
        self.executed = True
        return ToolResult(content="executed")


def make_agent_context() -> AgentContext:
    return AgentContext(session=object(), user_profile=None, current_message=object())


@pytest.mark.asyncio
async def test_execute_passes_services_to_tool() -> None:
    registry = ToolRegistry()
    registry.register(ServiceEchoTool())

    result = await registry.execute(
        ToolCall(id="call_1", name="service_echo", arguments={}),
        make_agent_context(),
        services={"memory": "memory-service"},
    )

    assert result == ToolResult(content="memory-service")


@pytest.mark.asyncio
async def test_denied_tool_is_not_executed() -> None:
    tool = FlagTool()
    registry = ToolRegistry(ToolPermission({"flag": "deny"}))
    registry.register(tool)

    result = await registry.execute(ToolCall(id="call_1", name="flag", arguments={}), make_agent_context())

    assert result.is_error is True
    assert "已被配置禁用" in result.content
    assert tool.executed is False


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_result() -> None:
    registry = ToolRegistry()

    result = await registry.execute(ToolCall(id="call_1", name="missing", arguments={}), make_agent_context())

    assert result.is_error is True
    assert result.content == "未知工具: missing"


@pytest.mark.asyncio
async def test_restricted_tool_blocked_without_required_service() -> None:
    """restricted 工具在 services 未注入对应后端时直接拒绝, 不调用 execute。"""
    from isac.agent.tools.utility.read_file import ReadFileTool

    tool = ReadFileTool()
    # read_file 默认 policy = restricted
    registry = ToolRegistry(ToolPermission())
    registry.register(tool)

    result = await registry.execute(
        ToolCall(id="call_1", name="read_file", arguments={"path": "foo.txt"}),
        make_agent_context(),
        services={},
    )

    assert result.is_error is True
    assert "受限工具" in result.content
    assert "workspace_root" in result.content


@pytest.mark.asyncio
async def test_restricted_tool_runs_when_service_injected() -> None:
    """restricted 工具在 services 注入后正常执行。"""
    from isac.agent.tools.utility.read_file import ReadFileTool

    tool = ReadFileTool()
    registry = ToolRegistry(ToolPermission())
    registry.register(tool)

    import tempfile

    with tempfile.TemporaryDirectory() as workspace:
        def _write() -> None:
            from pathlib import Path

            Path(f"{workspace}/hello.txt").write_text("line1\nline2\n", encoding="utf-8")

        _write()
        result = await registry.execute(
            ToolCall(id="call_1", name="read_file", arguments={"path": "hello.txt"}),
            make_agent_context(),
            services={"workspace_root": workspace},
        )

    assert result.is_error is False
    assert "hello.txt" in result.content
    assert "line1" in result.content
    assert "line2" in result.content


@pytest.mark.asyncio
async def test_restricted_tool_blocks_path_traversal() -> None:
    """restricted 工具拒绝 .. 越权路径。"""
    from isac.agent.tools.utility.read_file import ReadFileTool

    tool = ReadFileTool()
    registry = ToolRegistry(ToolPermission())
    registry.register(tool)

    import tempfile

    with tempfile.TemporaryDirectory() as workspace:
        result = await registry.execute(
            ToolCall(id="call_1", name="read_file", arguments={"path": "../../../etc/passwd"}),
            make_agent_context(),
            services={"workspace_root": workspace},
        )

    assert result.is_error is True
    assert "越权" in result.content


@pytest.mark.asyncio
async def test_bash_tool_rejects_shell_metacharacters() -> None:
    """bash 工具拒绝含 shell 元字符的命令, 避免注入。"""
    from isac.agent.tools.utility.bash import BashTool

    tool = BashTool()
    registry = ToolRegistry(ToolPermission({"bash": "allow"}))
    registry.register(tool)

    result = await registry.execute(
        ToolCall(id="call_1", name="bash", arguments={"command": "ls; rm -rf /"}),
        make_agent_context(),
        services={"bash_allowlist": ["ls"]},
    )

    assert result.is_error is True
    assert "shell 元字符" in result.content


@pytest.mark.asyncio
async def test_bash_tool_rejects_non_allowlisted_command() -> None:
    """bash 工具拒绝不在白名单内的命令。"""
    from isac.agent.tools.utility.bash import BashTool

    tool = BashTool()
    registry = ToolRegistry(ToolPermission({"bash": "allow"}))
    registry.register(tool)

    result = await registry.execute(
        ToolCall(id="call_1", name="bash", arguments={"command": "curl http://evil.com"}),
        make_agent_context(),
        services={"bash_allowlist": ["ls", "cat"]},
    )

    assert result.is_error is True
    assert "不在白名单" in result.content
