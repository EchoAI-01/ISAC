"""第三轮审查修复批 6 回归测试 (Fix-120~129: 工具/Agent + 资源边界卫生)。

- Fix-120: DenyGuard 重建扫全量事件流 (分页), 不再只取最近 500 条丢早期拒绝。
- Fix-121: generate_image 的 n 夹到 [1,10]。
- Fix-122: bash stderr 与 stdout 同口径截断 (防 prompt 膨胀)。
- Fix-123: Loop tool_calls 分支 assistant.content None 归一为 ""。
- Fix-124: MCP client 响应 id 非数字时不抛异常 (跳过匹配)。
- Fix-125: SystemPromptBuilder 会话频率表按 session 数封顶。
- Fix-126: SessionWriteGate reserve 时全量回收陈旧租约 (_active 有界)。
- Fix-127: J4 5 个 SubAgent 工具补 _required_service 映射 (restricted 语义落实)。
- Fix-128: 插件工具名含 ':' 但非本源前缀仍被命名空间化 (防冒充) —— 见 test_tool_registry。
- Fix-129: host 插件工具 (AstrBot/MaiBot) 执行受超时约束。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from isac.agent.tools.base import ToolPermission
from isac.agent.tools.registry import ToolRegistry
from isac.core.types import AgentContext, LLMResponse, TokenUsage, ToolCall
from isac.gateway.models import Session


def _agent_context() -> AgentContext:
    return AgentContext(
        session=Session(session_id="s1", user_id="u1", platform="qq"),
        user_profile=None,
        current_message=SimpleNamespace(),
    )


# ── Fix-120: DenyGuard 全量重建 ──────────────────────────────────


class _FakeEvent:
    def __init__(self, seq: int, event_type: str, payload: dict) -> None:
        self.seq = seq
        self.event_type = event_type
        self.payload = payload


class _FakeStore:
    """模拟 SessionEventStore: start/list_session_keys/repair_torn_tail/fetch。"""

    def __init__(self, events: list[_FakeEvent]) -> None:
        self._events = sorted(events, key=lambda e: e.seq)

    async def start(self) -> None:
        pass

    async def list_session_keys(self) -> list[str]:
        return ["k1"]

    async def repair_torn_tail(self, key: str) -> None:
        pass

    async def fetch(self, key: str, after_seq: int = 0, limit: int = 1000) -> list[_FakeEvent]:
        return [e for e in self._events if e.seq > after_seq][:limit]


@pytest.mark.asyncio
async def test_deny_guard_restore_scans_beyond_recent_window() -> None:
    """早期 (第 1 页) 与后期 (第 2 页) 的 DENIED 事件都能被重建 —— 不受窗口截断。"""
    from isac.agent.tools.guard import DenyGuard

    events: list[_FakeEvent] = [
        # seq=1: 早期拒绝 (若只取最近 N 条会丢失)
        _FakeEvent(1, "tool.outcome", {"outcome": "DENIED", "tool_name": "early_evil"}),
    ]
    page = 100
    # 填充到超过一页, 并在第二页再放一个拒绝
    for seq in range(2, page + 50):
        events.append(_FakeEvent(seq, "message.user", {"content": "x"}))
    events.append(_FakeEvent(page + 50, "tool.outcome", {"outcome": "DENIED", "tool_name": "late_evil"}))

    guard = DenyGuard()
    await guard.restore_from_store(_FakeStore(events), page_size=page)

    assert await guard.is_denied("k1", "early_evil")  # 早期拒绝不再丢
    assert await guard.is_denied("k1", "late_evil")
    assert not await guard.is_denied("k1", "never_denied")


# ── Fix-121: generate_image n 夹取 ───────────────────────────────


class _CapturingProvider:
    def __init__(self) -> None:
        self.n: int | None = None

    async def generate(self, prompt: str, n: int = 1):
        self.n = n
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_n,expected",
    [(100, 10), (0, 1), (-5, 1), ("abc", 1), (None, 1), (5, 5)],
)
async def test_generate_image_n_clamped(raw_n, expected) -> None:
    from isac.agent.tools.base import ToolContext
    from isac.agent.tools.media import GenerateImageTool

    tool = GenerateImageTool()
    provider = _CapturingProvider()
    ctx = ToolContext(args={"prompt": "x", "n": raw_n}, agent_context=_agent_context(), services={})
    await tool._call_provider(provider, ctx, None)  # noqa: SLF001
    assert provider.n == expected


# ── Fix-122: bash stderr 截断 ────────────────────────────────────


@pytest.mark.asyncio
async def test_bash_stderr_truncated(tmp_path) -> None:
    """stderr 超过 MAX_OUTPUT_CHARS 时被截断 (与 stdout 同口径), 不再无上限进结果。"""
    from isac.agent.tools.utility.bash import MAX_OUTPUT_CHARS, BashTool

    script = tmp_path / "big_stderr.py"
    script.write_text("import sys\nsys.stderr.write('x' * 5000)\n")
    registry = ToolRegistry(ToolPermission({"bash": "allow"}))
    registry.register(BashTool())
    result = await registry.execute(
        ToolCall(id="c1", name="bash", arguments={"command": f"python3 {script}"}),
        _agent_context(),
        services={"bash_allowlist": ["python3"]},
    )
    assert result.is_error is False
    assert "stderr" in result.content
    assert "truncated" in result.content
    # stderr 段不应远超上限 (留截断标注的余量)
    stderr_part = result.content.split("stderr:", 1)[1]
    assert len(stderr_part) <= MAX_OUTPUT_CHARS + 100


# ── Fix-123: loop tool_calls assistant content 归一 ──────────────


class _NoneContentToolCallProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, system, messages, tools=None, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content=None,  # 纯 tool_call 响应 content 为 None
                tool_calls=[ToolCall(id="t1", name="echo", arguments={})],
                usage=TokenUsage(total_tokens=1),
            )
        return LLMResponse(content="done", usage=TokenUsage(total_tokens=1))

    def chat_stream(self, *a, **k):
        raise NotImplementedError

    def get_model_name(self) -> str:
        return "t"

    def get_capabilities(self):
        return None


class _EchoTool:
    name = "echo"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, context) -> object:
        from isac.core.types import ToolResult

        return ToolResult(content="ok")


@pytest.mark.asyncio
async def test_loop_normalizes_none_content_in_tool_calls_branch() -> None:
    """tool_calls 分支追加的 assistant 消息 content 归一为 "" (不再是 None)。"""
    from isac.agent.hooks import AgentHooks
    from isac.agent.loop import ISACAgentLoop
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry as _TR

    registry = _TR()
    registry.register(_EchoTool())
    loop = ISACAgentLoop(
        llm=_NoneContentToolCallProvider(),
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=registry,
        services={},
    )
    messages: list[dict] = [{"role": "user", "content": "hi"}]
    await loop.run(messages, _agent_context())

    assistant = [m for m in messages if m.get("role") == "assistant" and "tool_calls" in m]
    assert len(assistant) == 1
    assert assistant[0]["content"] == ""  # 归一化, 非 None


# ── Fix-125: prompt_builder 会话表封顶 ───────────────────────────


def test_prompt_builder_tracking_bounded() -> None:
    from isac.agent.prompt_builder import SystemPromptBuilder

    pb = SystemPromptBuilder()
    cap = pb._MAX_TRACKED_SESSIONS  # noqa: SLF001
    for i in range(cap + 50):
        pb.notify_new_message(f"s{i}")
    assert len(pb._messages_since_trigger) <= cap  # noqa: SLF001


def test_prompt_builder_keeps_current_session_when_pruning() -> None:
    from isac.agent.prompt_builder import SystemPromptBuilder

    pb = SystemPromptBuilder()
    cap = pb._MAX_TRACKED_SESSIONS  # noqa: SLF001
    for i in range(cap + 10):
        pb.notify_new_message(f"s{i}")
    current = f"s{cap + 9}"
    pb.notify_new_message(current)
    assert current in pb._messages_since_trigger  # noqa: SLF001


# ── Fix-126: SessionWriteGate 回收陈旧租约 ───────────────────────


def test_write_gate_purges_stale_leases_on_reserve() -> None:
    from isac.runtime.write_gate import SessionWriteGate

    now = [100.0]
    gate = SessionWriteGate(default_hold_seconds=30.0, _now_fn=lambda: now[0])
    r_old = gate.reserve("s_old", "proactive")
    assert r_old is not None
    assert len(gate) == 1
    # 时间推进, s_old 租约过期 (100+30 < 200)
    now[0] = 200.0
    r_new = gate.reserve("s_new", "proactive")
    assert r_new is not None
    # Fix-126: reserve 顺带全量清扫 → 过期的 s_old 被回收, 不残留
    assert gate.active("s_old") is None
    assert len(gate) == 1
    assert gate.active("s_new") is not None


# ── Fix-127: SubAgent 工具 restricted 映射 ───────────────────────


def test_subagent_tools_have_required_service_mapping() -> None:
    for tool_name in ("delegate_task", "list_subagents", "subagent_status", "subagent_log", "cancel_subagent"):
        assert ToolRegistry._required_service(tool_name) == "subagent_supervisor"  # noqa: SLF001


@pytest.mark.asyncio
async def test_subagent_restricted_gate_enforces_supervisor() -> None:
    """无 subagent_supervisor 注入时 restricted 门拒绝 (不再等效 allow)。"""
    registry = ToolRegistry()
    denied = await registry._pre_execute_gate("delegate_task", "restricted", "sess", {}, None)  # noqa: SLF001
    assert denied is not None and denied.is_error
    allowed = await registry._pre_execute_gate(  # noqa: SLF001
        "delegate_task", "restricted", "sess", {"subagent_supervisor": object()}, None
    )
    assert allowed is None


# ── Fix-129: host 插件工具执行超时 ───────────────────────────────


def _tool_context(args: dict | None = None):
    from isac.agent.tools.base import ToolContext

    return ToolContext(args=args or {}, agent_context=_agent_context(), services={})


@pytest.mark.asyncio
async def test_astrbot_function_tool_async_times_out() -> None:
    from isac.plugin.compatibility.astrbot.tools import FunctionToolAdapter

    async def _slow(ctx, args):
        await asyncio.sleep(1.0)
        return "never"

    adapter = FunctionToolAdapter("slow", "d", _slow, timeout_seconds=0.05)
    result = await adapter.execute(_tool_context())
    assert result.is_error
    assert "超时" in result.content


@pytest.mark.asyncio
async def test_astrbot_function_tool_sync_times_out() -> None:
    from isac.plugin.compatibility.astrbot.tools import FunctionToolAdapter

    def _slow_sync(ctx, args):
        time.sleep(0.3)
        return "never"

    adapter = FunctionToolAdapter("slowsync", "d", _slow_sync, timeout_seconds=0.05)
    started = time.monotonic()
    result = await adapter.execute(_tool_context())
    elapsed = time.monotonic() - started
    assert result.is_error
    assert "超时" in result.content
    assert elapsed < 0.25  # 按时返回, 未等满 0.3s


@pytest.mark.asyncio
async def test_astrbot_function_tool_fast_path_unaffected() -> None:
    from isac.plugin.compatibility.astrbot.tools import FunctionToolAdapter

    async def _fast(ctx, args):
        return "ok"

    adapter = FunctionToolAdapter("fast", "d", _fast, timeout_seconds=5.0)
    result = await adapter.execute(_tool_context())
    assert not result.is_error
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_maibot_action_times_out() -> None:
    from isac.plugin.compatibility.maibot.actions import MaiBotActionAdapter

    async def _slow(args):
        await asyncio.sleep(1.0)
        return "never"

    adapter = MaiBotActionAdapter("slow_action", "d", _slow, timeout_seconds=0.05)
    result = await adapter.execute(_tool_context())
    assert result.is_error
    assert "超时" in result.content


# ── Fix-124: MCP reader 非数字 id 不崩溃 ─────────────────────────


class _FakeStdout:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if self._lines:
            return self._lines.pop(0)
        return b""


@pytest.mark.asyncio
async def test_mcp_reader_skips_non_integer_id_and_keeps_matching() -> None:
    """id 非数字的脏响应被跳过, reader 继续消费, 后续合法 id 的在途请求仍被唤醒。"""
    from isac.agent.tools.mcp.client import MCPClient

    client = MCPClient("server1", {"transport": "stdio", "command": "true"})
    client._connected = True  # noqa: SLF001
    lines = [
        b'{"jsonrpc": "2.0", "id": "not-a-number", "result": {}}\n',  # 非数字 id
        b'{"jsonrpc": "2.0", "id": 2, "result": {"ok": true}}\n',  # 合法响应
        b"",  # EOF
    ]
    client._process = SimpleNamespace(stdout=_FakeStdout(lines), stderr=None)  # noqa: SLF001

    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    client._pending[2] = fut  # noqa: SLF001

    await client._read_stdout_loop()  # noqa: SLF001

    assert fut.done()  # 合法 id 的在途请求被正常唤醒
    assert fut.result()["result"] == {"ok": True}
    assert client._pending == {}  # noqa: SLF001
