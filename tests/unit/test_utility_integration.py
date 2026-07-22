"""H3 实用工具与子 Agent 集成测试 - 受限策略 + 后端注入端到端。"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.agent.tools.base import ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.agent.tools.utility.bash import BashTool
from isac.agent.tools.utility.read_file import ReadFileTool
from isac.agent.tools.utility.task import TaskTool
from isac.agent.tools.utility.task_runner import TaskRunner
from isac.agent.tools.utility.web_search import WebSearchTool
from isac.agent.tools.utility.write_file import WriteFileTool
from isac.core.types import AgentContext, ToolCall, ToolResult
from isac.gateway.models import Session


def _make_agent_context() -> AgentContext:
    return AgentContext(
        session=Session(session_id="s1", user_id="u1", platform="qq"),
        user_profile=None,
        current_message=object(),
    )


class TestReadFileWriteFileIntegration:
    """read_file + write_file 完整受限链路。"""

    @pytest.mark.asyncio
    async def test_write_then_read_roundtrip(self, tmp_path: Path) -> None:
        registry = ToolRegistry(ToolPermission())
        registry.register(WriteFileTool())
        registry.register(ReadFileTool())

        # write
        write_result = await registry.execute(
            ToolCall(id="c1", name="write_file", arguments={"path": "data.txt", "content": "hello world"}),
            _make_agent_context(),
            services={"workspace_root": str(tmp_path)},
        )
        assert write_result.is_error is False
        assert (tmp_path / "data.txt").read_text() == "hello world"

        # read
        read_result = await registry.execute(
            ToolCall(id="c2", name="read_file", arguments={"path": "data.txt"}),
            _make_agent_context(),
            services={"workspace_root": str(tmp_path)},
        )
        assert read_result.is_error is False
        assert "hello world" in read_result.content

    @pytest.mark.asyncio
    async def test_path_traversal_blocked_in_write(self, tmp_path: Path) -> None:
        registry = ToolRegistry(ToolPermission())
        registry.register(WriteFileTool())
        result = await registry.execute(
            ToolCall(id="c1", name="write_file", arguments={"path": "../../etc/passwd", "content": "evil"}),
            _make_agent_context(),
            services={"workspace_root": str(tmp_path)},
        )
        assert result.is_error is True
        assert "越权" in result.content

    @pytest.mark.asyncio
    async def test_append_appends_existing_file(self, tmp_path: Path) -> None:
        registry = ToolRegistry(ToolPermission())
        registry.register(WriteFileTool())
        await registry.execute(
            ToolCall(id="c1", name="write_file", arguments={"path": "log.txt", "content": "line1"}),
            _make_agent_context(),
            services={"workspace_root": str(tmp_path)},
        )
        await registry.execute(
            ToolCall(id="c2", name="write_file", arguments={"path": "log.txt", "content": "line2", "append": True}),
            _make_agent_context(),
            services={"workspace_root": str(tmp_path)},
        )
        assert (tmp_path / "log.txt").read_text() == "line1line2"


class TestBashRestrictedPolicy:
    """bash 命令白名单 + 元字符防护。"""

    @pytest.mark.asyncio
    async def test_allowed_command_executes(self) -> None:
        registry = ToolRegistry(ToolPermission({"bash": "allow"}))
        registry.register(BashTool())
        result = await registry.execute(
            ToolCall(id="c1", name="bash", arguments={"command": "echo hello"}),
            _make_agent_context(),
            services={"bash_allowlist": ["echo", "ls"]},
        )
        assert result.is_error is False
        assert "hello" in result.content

    @pytest.mark.asyncio
    async def test_pipe_blocked(self) -> None:
        registry = ToolRegistry(ToolPermission({"bash": "allow"}))
        registry.register(BashTool())
        result = await registry.execute(
            ToolCall(id="c1", name="bash", arguments={"command": "echo a | cat"}),
            _make_agent_context(),
            services={"bash_allowlist": ["echo", "cat"]},
        )
        assert result.is_error is True
        assert "shell 元字符" in result.content

    @pytest.mark.asyncio
    async def test_redirect_blocked(self) -> None:
        registry = ToolRegistry(ToolPermission({"bash": "allow"}))
        registry.register(BashTool())
        result = await registry.execute(
            ToolCall(id="c1", name="bash", arguments={"command": "echo x > /tmp/evil"}),
            _make_agent_context(),
            services={"bash_allowlist": ["echo"]},
        )
        assert result.is_error is True
        assert "shell 元字符" in result.content


class TestWebSearchBackends:
    @pytest.mark.asyncio
    async def test_no_backend_returns_friendly_error(self) -> None:
        registry = ToolRegistry(ToolPermission())
        registry.register(WebSearchTool())
        result = await registry.execute(
            ToolCall(id="c1", name="web_search", arguments={"query": "test"}),
            _make_agent_context(),
            services={},
        )
        assert result.is_error is True
        assert "未配置 web_search" in result.content

    @pytest.mark.asyncio
    async def test_with_backend_returns_results(self) -> None:
        async def search(query: str, top_k: int = 5):
            return [{"title": "Result", "url": "https://x.com", "snippet": "snippet text"}]

        registry = ToolRegistry(ToolPermission())
        registry.register(WebSearchTool())
        result = await registry.execute(
            ToolCall(id="c1", name="web_search", arguments={"query": "test"}),
            _make_agent_context(),
            services={"web_search": search},
        )
        assert result.is_error is False
        assert "Result" in result.content
        assert "x.com" in result.content


class TestTaskRunner:
    """子 Agent 委派 (task_runner 真实实现)。"""

    @pytest.mark.asyncio
    async def test_task_tool_calls_runner(self) -> None:
        class _FakeRunner:
            def __init__(self) -> None:
                self.called_with: list[tuple[str, int]] = []

            async def __call__(self, task: str, *, budget: int, parent_context=None):
                self.called_with.append((task, budget))
                return ToolResult(content=f"子任务结果: {task[:20]}")

        runner = _FakeRunner()
        registry = ToolRegistry(ToolPermission({"task": "allow"}))
        registry.register(TaskTool())
        result = await registry.execute(
            ToolCall(id="c1", name="task", arguments={"task": "分析这段日志"}),
            _make_agent_context(),
            services={"task_runner": runner, "task_depth": 0, "task_max_depth": 3},
        )
        assert result.is_error is False
        assert "子任务结果" in result.content
        assert runner.called_with[0][0] == "分析这段日志"

    @pytest.mark.asyncio
    async def test_task_blocked_at_max_depth(self) -> None:
        registry = ToolRegistry(ToolPermission({"task": "allow"}))
        registry.register(TaskTool())
        result = await registry.execute(
            ToolCall(id="c1", name="task", arguments={"task": "再委派一层"}),
            _make_agent_context(),
            services={
                "task_runner": lambda *a, **kw: ToolResult(content="should not be called"),
                "task_depth": 3,
                "task_max_depth": 3,
            },
        )
        assert result.is_error is True
        assert "递归深度已达上限" in result.content

    def test_task_runner_initializes_with_loop(self) -> None:
        # TaskRunner 构造能拿到 loop 引用 (不实际执行)
        class _FakeLoop:
            pass

        runner = TaskRunner(_FakeLoop())
        assert runner.default_budget == 2000
