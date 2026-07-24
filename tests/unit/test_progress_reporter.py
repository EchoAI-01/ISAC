"""D9 任务进度报告框架骨架测试。

验证契约与控制流就位, 且默认关闭时主链路零行为变化。复杂逻辑 (跨窗口合并、
LLM 改写) 属实现节点范畴, 本文件只覆盖骨架级行为。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from isac.agent.hooks import AgentHooks
from isac.agent.loop import ISACAgentLoop
from isac.agent.prompt_builder import SystemPromptBuilder
from isac.agent.tools.base import Tool, ToolContext
from isac.agent.tools.registry import ToolRegistry
from isac.core.types import AgentContext, ProgressEvent, ToolResult
from isac.runtime.progress import (
    PersonaProgressRenderer,
    ProgressPolicy,
    ProgressReporter,
    build_progress_reporter,
)
from tests.fixtures.fakes import FakeLLMProvider, make_final_reply, make_tool_call_response


class _SlowTool(Tool):
    """D9-2 测试用工具: 固定延时后返回, 用于验证慢工具前置 tool_started 事件。"""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    @property
    def name(self) -> str:
        return "query_memory"

    @property
    def description(self) -> str:
        return "test slow tool"

    async def execute(self, context: ToolContext) -> ToolResult:
        if self._delay:
            await asyncio.sleep(self._delay)
        return ToolResult(content="tool done")


def _event(stage: str = "tool_finished", *, task_id: str = "t1", occurred_at: float = 100.0, **kw) -> ProgressEvent:
    return ProgressEvent(
        event_id="e1",
        task_id=task_id,
        agent_id="a1",
        session_id="s1",
        stage=stage,
        occurred_at=occurred_at,
        **kw,
    )


def test_policy_from_config_ignores_unknown_keys() -> None:
    policy = ProgressPolicy.from_config({"enabled": False, "min_interval_seconds": 5.0, "bogus": 1})
    assert policy.enabled is False
    assert policy.min_interval_seconds == 5.0
    assert not hasattr(policy, "bogus")


def test_renderer_templates_each_stage_without_raw_args() -> None:
    renderer = PersonaProgressRenderer(mode="template")
    text = renderer.render(_event("tool_finished", tool_name="query_memory"))
    assert "query_memory" in text
    # 模板不回显原始参数字典
    assert "arguments" not in text


def test_renderer_llm_mode_falls_back_to_template() -> None:
    # 骨架阶段 llm 模式不真正调模型, 回退模板且不抛异常
    renderer = PersonaProgressRenderer(mode="llm")
    assert renderer.render(_event("completed")) != ""


async def test_reporter_dispatches_when_enabled() -> None:
    sent: list[tuple[str, ProgressEvent]] = []

    async def sender(text: str, event: ProgressEvent) -> None:
        sent.append((text, event))

    reporter = build_progress_reporter(agent_id="a1", session_id="s1", sender=sender)
    assert await reporter.report(_event("tool_finished", tool_name="bash")) is True
    assert len(sent) == 1
    assert "bash" in sent[0][0]


async def test_reporter_disabled_policy_skips() -> None:
    sent: list[str] = []

    async def sender(text: str, event: ProgressEvent) -> None:
        sent.append(text)

    reporter = ProgressReporter(
        agent_id="a1", session_id="s1", policy=ProgressPolicy(enabled=False), sender=sender
    )
    assert await reporter.report(_event("tool_finished")) is False
    assert sent == []


async def test_reporter_enforces_visible_cap() -> None:
    reporter = ProgressReporter(
        agent_id="a1",
        session_id="s1",
        policy=ProgressPolicy(max_visible_events_per_task=2, min_interval_seconds=0.0),
        sender=_noop_sender,
    )
    assert await reporter.report(_event("tool_finished", occurred_at=1.0)) is True
    assert await reporter.report(_event("tool_finished", occurred_at=2.0)) is True
    # 第三条超过每任务上限, 被拒
    assert await reporter.report(_event("tool_finished", occurred_at=3.0)) is False


async def test_reporter_terminal_stage_bypasses_interval() -> None:
    reporter = ProgressReporter(
        agent_id="a1",
        session_id="s1",
        policy=ProgressPolicy(min_interval_seconds=999.0),
        sender=_noop_sender,
    )
    # 普通阶段受最小间隔约束 (首条 last_emit=0 时 100-0>=999 为假) → 拒绝
    assert await reporter.report(_event("tool_started", occurred_at=100.0)) is False
    # 终态阶段绕过间隔 → 放行
    assert await reporter.report(_event("completed", occurred_at=100.0)) is True


async def test_reporter_sanitizes_sensitive_metadata() -> None:
    captured: list[ProgressEvent] = []

    async def sender(text: str, event: ProgressEvent) -> None:
        captured.append(event)

    reporter = build_progress_reporter(agent_id="a1", session_id="s1", sender=sender)
    await reporter.report(_event("tool_finished", metadata={"api_key": "sk-x", "safe": "ok"}))
    assert captured[0].metadata == {"safe": "ok"}


async def test_reporter_swallows_sender_errors() -> None:
    async def boom(text: str, event: ProgressEvent) -> None:
        raise RuntimeError("channel down")

    reporter = build_progress_reporter(agent_id="a1", session_id="s1", sender=boom)
    # 发送失败不得冒泡, 只返回 False
    assert await reporter.report(_event("tool_finished")) is False


async def test_loop_emit_progress_is_inert_without_callback() -> None:
    loop = _make_loop()
    # report_progress 默认 None → 直接返回, 即使 session 是裸对象也不访问其属性
    ctx = AgentContext(session=object(), user_profile=None, current_message=object())
    await loop._emit_progress(ctx, "tool_finished", tool_name="x")  # 不抛异常即通过


async def test_loop_emit_progress_invokes_callback_when_set() -> None:
    received: list[ProgressEvent] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event)

    loop = _make_loop()
    ctx = AgentContext(
        session=SimpleNamespace(session_id="s1"),
        user_profile=None,
        current_message=object(),
        report_progress=cb,
    )
    await loop._emit_progress(ctx, "tool_finished", tool_name="query_memory")
    assert len(received) == 1
    assert received[0].stage == "tool_finished"
    assert received[0].tool_name == "query_memory"
    assert received[0].session_id == "s1"


async def _noop_sender(text: str, event: ProgressEvent) -> None:
    return None


def _make_loop(llm: object = None, tools: ToolRegistry | None = None) -> ISACAgentLoop:
    return ISACAgentLoop(
        llm=llm or object(),  # type: ignore[arg-type]
        prompt_builder=SystemPromptBuilder(),
        hooks=AgentHooks(),
        tools=tools or ToolRegistry(),
    )


def _make_context(report_progress=None, services: dict | None = None) -> AgentContext:
    return AgentContext(
        session=SimpleNamespace(session_id="s1"),
        user_profile=None,
        current_message=object(),
        report_progress=report_progress,
        services=services or {},
    )


async def test_loop_does_not_emit_planned_or_completed_for_simple_reply_without_tools() -> None:
    """单轮无工具调用的简单回复不产生 planned/completed 噪音 (D9)。"""
    received: list[str] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event.stage)

    provider = FakeLLMProvider(scripted_replies=[make_final_reply("done")])
    loop = _make_loop(llm=provider)
    ctx = _make_context(report_progress=cb)

    result = await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert result.content == "done"
    assert received == []


async def test_loop_emits_planned_before_first_tool_call() -> None:
    received: list[ProgressEvent] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event)

    provider = FakeLLMProvider(
        scripted_replies=[make_tool_call_response("query_memory"), make_final_reply("done")]
    )
    tools = ToolRegistry()
    tools.register(_SlowTool(delay=0.0))
    loop = _make_loop(llm=provider, tools=tools)
    ctx = _make_context(report_progress=cb)

    await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert received[0].stage == "planned"


async def test_loop_emits_completed_before_returning_final_content_after_tool_task() -> None:
    received: list[ProgressEvent] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event)

    provider = FakeLLMProvider(
        scripted_replies=[make_tool_call_response("query_memory"), make_final_reply("done")]
    )
    tools = ToolRegistry()
    tools.register(_SlowTool(delay=0.0))
    loop = _make_loop(llm=provider, tools=tools)
    ctx = _make_context(report_progress=cb)

    result = await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert result.content == "done"
    assert received[-1].stage == "completed"


async def test_loop_does_not_emit_interrupted_without_prior_task_progress() -> None:
    """打断发生在还没报告过任何进度的单轮请求上时, 不产生多余的 interrupted 事件。"""
    received: list[ProgressEvent] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event)

    provider = FakeLLMProvider(scripted_replies=[make_final_reply("done")])
    loop = _make_loop(llm=provider)
    ctx = _make_context(report_progress=cb)
    ctx.interrupt_requested = True

    result = await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert result.interrupted is True
    assert received == []


async def test_loop_emits_interrupted_after_task_already_reported() -> None:
    """已经报告过 planned (工具调用已开始) 的任务被打断时, 应发一条 interrupted 收束。"""
    received: list[str] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event.stage)

    ctx = _make_context(report_progress=cb)

    class _InterruptOnSecondCallProvider:
        def __init__(self) -> None:
            self.call_count = 0

        async def chat(self, system, messages, tools=None, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                return make_tool_call_response("query_memory")
            ctx.interrupt_requested = True
            return make_final_reply("unused")

        async def chat_stream(self, *args, **kwargs):
            raise NotImplementedError

        def get_model_name(self) -> str:
            return "interrupt-test"

        def get_capabilities(self):
            return None

    tools = ToolRegistry()
    tools.register(_SlowTool(delay=0.0))
    loop = _make_loop(llm=_InterruptOnSecondCallProvider(), tools=tools)

    result = await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert result.interrupted is True
    assert "planned" in received
    assert received[-1] == "interrupted"


async def test_loop_emits_tool_started_before_slow_tool_finishes() -> None:
    received: list[str] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event.stage)

    provider = FakeLLMProvider(
        scripted_replies=[make_tool_call_response("query_memory"), make_final_reply("done")]
    )
    tools = ToolRegistry()
    tools.register(_SlowTool(delay=0.05))
    loop = _make_loop(llm=provider, tools=tools)
    ctx = _make_context(report_progress=cb, services={"progress_slow_tool_threshold_seconds": 0.01})

    await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert "tool_started" in received
    assert received.index("tool_started") < received.index("tool_finished")


async def test_loop_does_not_emit_tool_started_for_fast_tool() -> None:
    received: list[str] = []

    async def cb(event: ProgressEvent) -> None:
        received.append(event.stage)

    provider = FakeLLMProvider(
        scripted_replies=[make_tool_call_response("query_memory"), make_final_reply("done")]
    )
    tools = ToolRegistry()
    tools.register(_SlowTool(delay=0.0))
    loop = _make_loop(llm=provider, tools=tools)
    ctx = _make_context(report_progress=cb, services={"progress_slow_tool_threshold_seconds": 1.0})

    await loop.run([{"role": "user", "content": "hi"}], ctx)

    assert "tool_started" not in received


async def test_loop_slow_tool_sentinel_does_not_leak_task_when_disabled() -> None:
    """report_progress 为 None 时不应额外创建哨兵任务 (零行为变化)。"""
    provider = FakeLLMProvider(
        scripted_replies=[make_tool_call_response("query_memory"), make_final_reply("done")]
    )
    tools = ToolRegistry()
    tools.register(_SlowTool(delay=0.0))
    loop = _make_loop(llm=provider, tools=tools)
    ctx = _make_context(report_progress=None)

    pending_before = len(asyncio.all_tasks())
    result = await loop.run([{"role": "user", "content": "hi"}], ctx)
    pending_after = len(asyncio.all_tasks())

    assert result.content == "done"
    assert pending_after == pending_before
