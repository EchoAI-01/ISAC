"""H3 实用工具与子 Agent 集成测试 - 受限策略 + 后端注入端到端。"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.agent.hooks import AgentHooks
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import Tool, ToolContext, ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.agent.tools.utility.bash import BashTool
from isac.agent.tools.utility.read_file import ReadFileTool
from isac.agent.tools.utility.task import TaskTool
from isac.agent.tools.utility.task_runner import TaskRunner, make_task_runner
from isac.agent.tools.utility.web_search import WebSearchTool
from isac.agent.tools.utility.write_file import WriteFileTool
from isac.core.types import AgentContext, LLMResponse, TokenUsage, ToolCall, ToolResult
from isac.gateway.models import Session


def _make_agent_context() -> AgentContext:
    return AgentContext(
        session=Session(session_id="s1", user_id="u1", platform="qq"),
        user_profile=None,
        current_message=object(),
    )


class _DepthPeekTool(Tool):
    """记录调用时 services["task_depth"] 的值, 供 Fix-34 测试断言子任务实际看到的深度。"""

    def __init__(self, sink: list[int]) -> None:
        self._sink = sink

    @property
    def name(self) -> str:
        return "peek_depth"

    @property
    def description(self) -> str:
        return "记录当前 task_depth"

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, context: ToolContext) -> ToolResult:
        self._sink.append(int(context.services.get("task_depth", -1)))
        return ToolResult(content="ok")


class _PeekThenDoneProvider:
    """第一次 chat() 触发 peek_depth 工具调用, 第二次返回最终回复 (模拟子任务执行者)。"""

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, system, messages, tools=None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="",
                tool_calls=[ToolCall(id="c1", name="peek_depth", arguments={})],
                usage=TokenUsage(total_tokens=1),
            )
        return LLMResponse(content="子任务完成", usage=TokenUsage(total_tokens=1))

    def chat_stream(self, system, messages, tools=None, **kwargs):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "test"

    def get_capabilities(self):
        return None


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
    async def test_default_policy_denies_web_search(self) -> None:
        """Q0: 无搜索后端实现, 默认策略 deny (不再出现在 LLM schema 里恒失败)。"""
        registry = ToolRegistry(ToolPermission())
        registry.register(WebSearchTool())
        result = await registry.execute(
            ToolCall(id="c1", name="web_search", arguments={"query": "test"}),
            _make_agent_context(),
            services={},
        )
        assert result.is_error is True
        assert "禁用" in result.content

    @pytest.mark.asyncio
    async def test_no_backend_returns_friendly_error(self) -> None:
        """显式 allow 但未注入后端时, 工具自身返回友好错误 (Q0 后需显式开启)。"""
        registry = ToolRegistry(ToolPermission({"web_search": "allow"}))
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

        registry = ToolRegistry(ToolPermission({"web_search": "allow"}))
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

            async def __call__(
                self, task: str, *, budget: int, parent_context=None, depth: int = 0, max_depth: int = 3
            ):
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

    @pytest.mark.asyncio
    async def test_task_runner_child_loop_gets_incremented_depth_without_polluting_parent(self) -> None:
        """Fix-34: 子任务在独立的 loop 实例里执行, services["task_depth"] 正确
        +1 传给子任务, 且不会污染宿主 loop 自己的 services —— 证明两者不再共享
        同一个可变 dict (修复前 task_depth 完全不会被设置或传递, 递归深度限制
        对这条旧路径形同虚设)。"""
        depths_seen: list[int] = []
        provider = _PeekThenDoneProvider()
        registry = ToolRegistry()
        registry.register(_DepthPeekTool(depths_seen))
        parent_loop = ISACAgentLoop(
            llm=provider,
            prompt_builder=SystemPromptBuilder(),
            hooks=AgentHooks(),
            tools=registry,
            services={"task_depth": 0, "static_service": "x"},
        )
        runner = TaskRunner(parent_loop)

        result = await runner.run(
            "子任务描述", budget=1000, parent_context=_make_agent_context(), depth=0, max_depth=3
        )

        assert result.is_error is not True
        assert "子任务完成" in result.content
        assert depths_seen == [1]  # 子任务看到的 task_depth 正确从 0 +1
        # 宿主 loop 自己的 services 未被污染 (仍是构造时传入的原值)
        assert parent_loop.services["task_depth"] == 0
        assert parent_loop.services["static_service"] == "x"

    @pytest.mark.asyncio
    async def test_task_runner_rejects_at_max_depth_without_invoking_child_loop(self) -> None:
        """depth>=max_depth 时 TaskRunner 应自行拒绝, 不构造/执行子任务 loop——
        与 SubAgentSupervisor.submit 对 depth 的独立校验同一 "各层自己把关"
        思路, 不完全依赖调用方 (TaskTool) 有没有先检查过。"""
        provider = _PeekThenDoneProvider()
        registry = ToolRegistry()
        registry.register(_DepthPeekTool([]))
        parent_loop = ISACAgentLoop(
            llm=provider, prompt_builder=SystemPromptBuilder(), hooks=AgentHooks(), tools=registry, services={}
        )
        runner = TaskRunner(parent_loop)

        result = await runner.run(
            "再深一层", budget=1000, parent_context=_make_agent_context(), depth=3, max_depth=3
        )

        assert result.is_error is True
        assert "递归深度已达上限" in result.content
        assert provider.calls == 0  # 未曾构造/调用子任务 loop

    @pytest.mark.asyncio
    async def test_task_tool_forwards_depth_to_real_task_runner(self) -> None:
        """Fix-34 集成: TaskTool.execute() 必须把自己读到的 depth/max_depth 转发
        给 task_runner, 不能像修复前那样完全不传——否则 runner 侧无从得知当前
        递归深度, 子任务里再嵌套委派时深度会被当成 0 重新计数。用
        make_task_runner 工厂产出的真实可调用对象 (而非手动 runner.run), 一并
        覆盖工厂本身的返回值可调用性。"""
        depths_seen: list[int] = []
        provider = _PeekThenDoneProvider()
        child_registry = ToolRegistry()
        child_registry.register(_DepthPeekTool(depths_seen))
        parent_loop = ISACAgentLoop(
            llm=provider, prompt_builder=SystemPromptBuilder(), hooks=AgentHooks(), tools=child_registry, services={}
        )
        runner = make_task_runner(parent_loop)
        task_registry = ToolRegistry(ToolPermission({"task": "allow"}))
        task_registry.register(TaskTool())

        result = await task_registry.execute(
            ToolCall(id="c1", name="task", arguments={"task": "委派一层"}),
            _make_agent_context(),
            services={"task_runner": runner, "task_depth": 2, "task_max_depth": 5},
        )

        assert result.is_error is False
        assert depths_seen == [3]  # 2 (调用方深度) + 1, 正确从 TaskTool 转发到 TaskRunner
