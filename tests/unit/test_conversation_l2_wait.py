"""L2 Wait 闭环业务测试。

覆盖:
- ConversationRuntime.should_trigger 真实 debounce 判定 (zero / positive)
- enter_wait 启动超时定时器 + 状态转移 WAITING
- resolve_wait 回填 end_reason + actual_seconds + 取消定时器
- notify_new_message 在 WAITING 时结束 wait (MESSAGE 原因)
- 超时定时器到期触发 resolve_wait (TIMEOUT 原因)
- WaitTool enabled=False 返回意图字符串 (零行为变化)
- WaitTool enabled=True 注册 WaitState 并 await future
- 三条唤醒路径 (message/timeout/proactive) 各自回填 end_reason
"""

from __future__ import annotations

import asyncio

import pytest

from isac.agent.tools.base import ToolContext
from isac.agent.tools.social.wait import WaitTool
from isac.channel.model import ISACMessage
from isac.core.types import AgentContext
from isac.gateway.models import Session
from isac.runtime.conversation import (
    ConversationRuntime,
    ConversationRuntimeRegistry,
    WaitEndReason,
    WaitState,
)


def _make_message(content: str = "hi") -> ISACMessage:
    return ISACMessage(msg_id="m1", platform="webchat", timestamp=0, user_id="u1", user_name="u", content=content)


def _make_session(session_id: str = "s1") -> Session:
    return Session(session_id=session_id, user_id="u1", platform="webchat")


def _make_agent_context(session: Session | None = None) -> AgentContext:
    return AgentContext(session=session or _make_session(), user_profile=None, current_message=_make_message())


def test_should_trigger_zero_debounce_always_true() -> None:
    runtime = ConversationRuntime("a1", "s1")
    runtime.last_message_received_at = 100.0
    assert runtime.should_trigger(debounce_seconds=0.0) is True


def test_register_message_caps_cache_size_and_adjusts_processed_index() -> None:
    """CR2-Fix-4: register_message 是当前唯一在生产环境被 manager 真实调用的写入
    路径 (drain_new_messages 从未被生产代码调用), 长会话下 message_cache 会无界
    增长。应有软上限, 超出后丢弃最旧消息并同步下修 last_processed_index。"""
    from isac.runtime.conversation.runtime import _MAX_MESSAGE_CACHE

    runtime = ConversationRuntime("a1", "s1")
    for i in range(_MAX_MESSAGE_CACHE + 50):
        runtime.register_message(_make_message(f"m{i}"))
    assert len(runtime.message_cache) == _MAX_MESSAGE_CACHE
    # 最旧的 50 条应已被丢弃, 缓存里第一条应是 m50
    assert runtime.message_cache[0].content == "m50"
    assert runtime.last_processed_index == 0  # 从未 drain 过, 索引应保持在 0 (被 max(0,...) 夹住)


def test_should_trigger_positive_respects_silence_window() -> None:
    runtime = ConversationRuntime("a1", "s1")
    runtime.last_message_received_at = 100.0
    assert runtime.should_trigger(debounce_seconds=5.0, now=103.0) is False
    assert runtime.should_trigger(debounce_seconds=5.0, now=105.1) is True


@pytest.mark.asyncio
async def test_enter_wait_transitions_to_waiting() -> None:
    runtime = ConversationRuntime("a1", "s1")
    wait = WaitState(tool_call_id="c1", started_at=10.0, requested_seconds=5.0)
    await runtime.enter_wait(wait)
    assert runtime.state.value == "waiting"
    assert runtime.pending_wait is wait


@pytest.mark.asyncio
async def test_resolve_wait_records_end_reason_and_actual_seconds() -> None:
    runtime = ConversationRuntime("a1", "s1")
    wait = WaitState(tool_call_id="c1", started_at=10.0)
    await runtime.enter_wait(wait)
    resolved = runtime.resolve_wait(WaitEndReason.MESSAGE)
    assert resolved is not None
    assert resolved.end_reason is WaitEndReason.MESSAGE
    assert resolved.actual_seconds >= 0.0
    assert runtime.state.value == "idle"
    assert runtime.pending_wait is None


@pytest.mark.asyncio
async def test_resolve_wait_returns_none_when_not_waiting() -> None:
    runtime = ConversationRuntime("a1", "s1")
    assert runtime.resolve_wait(WaitEndReason.MESSAGE) is None


@pytest.mark.asyncio
async def test_timeout_task_fires_after_requested_seconds() -> None:
    runtime = ConversationRuntime("a1", "s1")
    wait = WaitState(tool_call_id="c1", started_at=0.0, requested_seconds=0.05)
    await runtime.enter_wait(wait)
    # 等待足够时间让超时 task 触发
    await asyncio.sleep(0.15)
    assert runtime.pending_wait is None
    assert runtime.state.value == "idle"


@pytest.mark.asyncio
async def test_notify_new_message_ends_wait_with_message_reason() -> None:
    runtime = ConversationRuntime("a1", "s1")
    wait = WaitState(tool_call_id="c1", started_at=0.0, requested_seconds=10.0)
    await runtime.enter_wait(wait)
    runtime.notify_new_message()
    assert runtime.pending_wait is None
    assert wait.end_reason is WaitEndReason.MESSAGE


@pytest.mark.asyncio
async def test_resolve_wait_cancels_pending_timeout_task() -> None:
    runtime = ConversationRuntime("a1", "s1")
    wait = WaitState(tool_call_id="c1", started_at=0.0, requested_seconds=10.0)
    await runtime.enter_wait(wait)
    runtime.resolve_wait(WaitEndReason.MESSAGE)
    # 等一段时间确认 timeout task 已被 cancel, 没有触发
    await asyncio.sleep(0.05)
    assert runtime.state.value == "idle"


@pytest.mark.asyncio
async def test_wait_tool_enabled_false_returns_intent_string() -> None:
    """enabled=False 时 WaitTool 返回意图字符串, 不进入 runtime (零行为变化)."""
    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)
    # services 不含 conversation_enabled (默认 False) — 退化为意图字符串
    ctx = ToolContext(args={"seconds": 5}, agent_context=agent_context, services={})
    result = await tool.execute(ctx)
    assert "等待" in result.content
    assert "s1" in result.content  # session_id 占位回填


@pytest.mark.asyncio
async def test_wait_tool_enabled_true_registers_and_resolves_on_timeout() -> None:
    """enabled=True 时 WaitTool 注册 WaitState 并 await future, 超时后被唤醒."""
    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)
    registry = ConversationRuntimeRegistry()
    services = {"conversation_registry": registry, "conversation_enabled": True, "agent_id": "a1"}
    ctx = ToolContext(args={"seconds": 1}, agent_context=agent_context, services=services)
    task = asyncio.create_task(tool.execute(ctx))
    await asyncio.sleep(0.05)  # 让工具 enter_wait 注册 WaitState
    runtime = registry.get("a1", "s1")
    assert runtime.state.value == "waiting"
    # 超时 1 秒后唤醒 (requested_seconds=1.0)
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "等待" in result.content
    assert "超时" in result.content or "timeout" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_tool_resolves_on_new_message() -> None:
    """enabled=True 时新消息到达唤醒 wait (MESSAGE 原因)."""
    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)
    registry = ConversationRuntimeRegistry()
    services = {"conversation_registry": registry, "conversation_enabled": True, "agent_id": "a1"}
    ctx = ToolContext(args={"seconds": 30}, agent_context=agent_context, services=services)
    task = asyncio.create_task(tool.execute(ctx))
    await asyncio.sleep(0.05)
    runtime = registry.get("a1", "s1")
    runtime.notify_new_message()
    result = await asyncio.wait_for(task, timeout=1.0)
    assert "新消息" in result.content or "message" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_tool_seconds_zero_still_resolves_via_timeout() -> None:
    """CR2-Fix-2: seconds<=0 (LLM 可能传负数, "0" 字面值因 `or 5` 短路已被当成 5)
    不应变成 requested_seconds=None (不创建超时定时器); 否则在 MESSAGE/PROACTIVE
    均未被触发的场景下会永久挂起。应有一个最小下限。"""
    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)
    registry = ConversationRuntimeRegistry()
    services = {"conversation_registry": registry, "conversation_enabled": True, "agent_id": "a1"}
    ctx = ToolContext(args={"seconds": -1}, agent_context=agent_context, services=services)
    task = asyncio.create_task(tool.execute(ctx))
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "超时" in result.content or "timeout" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_tool_resolves_on_proactive() -> None:
    """主动任务唤醒 wait (PROACTIVE 原因)."""
    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)
    registry = ConversationRuntimeRegistry()
    services = {"conversation_registry": registry, "conversation_enabled": True, "agent_id": "a1"}
    ctx = ToolContext(args={"seconds": 30}, agent_context=agent_context, services=services)
    task = asyncio.create_task(tool.execute(ctx))
    await asyncio.sleep(0.05)
    runtime = registry.get("a1", "s1")
    runtime.resolve_wait(WaitEndReason.PROACTIVE)
    result = await asyncio.wait_for(task, timeout=1.0)
    assert "主动" in result.content or "proactive" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_tool_hard_timeout_when_future_never_resolves() -> None:
    """R18: await_wait future 永不 resolve (协程被取消/lock 释放异常) 时,
    asyncio.wait_for hard timeout 兜底返回, 不永久挂起。

    构造一个 stub runtime, await_wait 返回永不 resolve 的 future。
    """
    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)

    class _StubRuntime:
        """模拟 runtime: enter_wait 不做事, await_wait 返回永不 resolve 的 future。"""

        def __init__(self) -> None:
            self._future: asyncio.Future = asyncio.Future()

        async def enter_wait(self, wait: WaitState) -> None:
            return None

        async def await_wait(self, tool_call_id: str) -> WaitState:
            return await self._future  # 永不 resolve

    class _StubRegistry:
        def get(self, agent_id: str, session_id: str) -> _StubRuntime:
            return _stub_runtime

    _stub_runtime = _StubRuntime()
    stub_registry = _StubRegistry()
    services = {
        "conversation_registry": stub_registry,
        "conversation_enabled": True,
        "agent_id": "a1",
    }
    ctx = ToolContext(args={"seconds": 1}, agent_context=agent_context, services=services)
    # 不应永久挂起; hard cap = seconds + 1 = 2 秒
    result = await asyncio.wait_for(tool.execute(ctx), timeout=5.0)
    assert "超时" in result.content or "timeout" in result.content.lower()
    assert "hard cap" in result.content or "hard" in result.content.lower()


@pytest.mark.asyncio
async def test_wait_tool_hard_timeout_cleans_up_real_runtime_state() -> None:
    """Fix-33: 硬超时兜底触发时 (模拟内部软超时定时器因故未能触发, R18 场景注释
    所指"协程被取消/lock 释放"等异常), 必须清理 runtime 的 pending_wait/state/
    _timeout_tasks, 不能让该会话永久停在 WAITING —— 用真实 ConversationRuntime
    (而非上面 test_wait_tool_hard_timeout_when_future_never_resolves 用的最小
    stub) 验证硬超时返回后状态被正确复位, 且伪造的悬挂定时器任务被取消清理。"""

    async def _hang_forever(wait: WaitState) -> None:
        await asyncio.sleep(100)  # 模拟内部软超时定时器因故未能触发

    tool = WaitTool()
    session = _make_session()
    agent_context = _make_agent_context(session)
    registry = ConversationRuntimeRegistry()
    runtime = registry.get("a1", "s1")  # 预先取出同一实例, 抢在 WaitTool 调用前打补丁
    runtime._wait_timeout = _hang_forever  # type: ignore[method-assign]
    services = {"conversation_registry": registry, "conversation_enabled": True, "agent_id": "a1"}
    ctx = ToolContext(args={"seconds": 1}, agent_context=agent_context, services=services)

    result = await asyncio.wait_for(tool.execute(ctx), timeout=5.0)  # hard cap = 2s

    assert "超时" in result.content or "timeout" in result.content.lower()
    assert runtime.state.value == "idle"  # Fix-33 前: 会永久停在 waiting
    assert runtime.pending_wait is None
    assert len(runtime._timeout_tasks) == 0  # 伪造的悬挂定时器任务应已被取消清理
