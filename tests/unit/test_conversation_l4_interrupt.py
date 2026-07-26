"""L4 Planner 打断业务测试。

覆盖:
- ConversationRuntime.interrupt_state + request_interrupt 单轮次数限制
- request_interrupt 置 superseded=True + interrupt_count 累加
- clear_interrupt 重置状态 (供 AgentLoop 进入下一轮前调用)
- InterruptInjector 注入"上一轮被打断"提示 (interrupt_count > 0 时)
- InterruptInjector 无提示 (未打断时)
- AgentLoop 在 thinking 后读 runtime.interrupt_state.superseded 中断本轮
- enabled=False 主链路零行为变化
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from isac.agent.injectors.interrupt import InterruptInjector
from isac.gateway.models import Session
from isac.runtime.conversation import ConversationRuntime


def _make_session(session_id: str = "s1") -> Session:
    return Session(session_id=session_id, user_id="u1", platform="webchat")


def _make_injection_context(session_id: str = "s1") -> SimpleNamespace:
    return SimpleNamespace(session=_make_session(session_id))


# ── ConversationRuntime.interrupt_state ──────────────────────────


def test_runtime_initial_interrupt_state_is_none() -> None:
    runtime = ConversationRuntime("a1", "s1")
    assert runtime.interrupt_state is None


def test_runtime_request_interrupt_first_time_allowed() -> None:
    runtime = ConversationRuntime("a1", "s1", max_interrupts_per_turn=1)
    assert runtime.request_interrupt(reason="新消息") is True
    assert runtime.interrupt_state is not None
    assert runtime.interrupt_state.interrupt_count == 1
    assert runtime.interrupt_state.superseded is True
    assert runtime.interrupt_state.reason == "新消息"


def test_runtime_request_interrupt_second_time_same_turn_rejected() -> None:
    """单轮打断次数上限 (默认 1): 第二次请求被拒绝."""
    runtime = ConversationRuntime("a1", "s1", max_interrupts_per_turn=1)
    assert runtime.request_interrupt() is True
    assert runtime.request_interrupt() is False  # 已达上限
    assert runtime.interrupt_state.interrupt_count == 1  # 不累加


def test_runtime_clear_interrupt_resets_state() -> None:
    """AgentLoop 进入下一轮前调 clear_interrupt, 重置状态."""
    runtime = ConversationRuntime("a1", "s1", max_interrupts_per_turn=1)
    runtime.request_interrupt()
    assert runtime.interrupt_state is not None
    runtime.clear_interrupt()
    assert runtime.interrupt_state is None
    # 清空后可再次打断
    assert runtime.request_interrupt() is True


def test_runtime_request_interrupt_max_interrupts_configurable() -> None:
    """max_interrupts_per_turn 可配置; 默认 1."""
    runtime = ConversationRuntime("a1", "s1", max_interrupts_per_turn=2)
    assert runtime.request_interrupt() is True
    assert runtime.request_interrupt() is True
    assert runtime.request_interrupt() is False  # 第三次拒绝
    assert runtime.interrupt_state.interrupt_count == 2


# ── InterruptInjector ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_interrupt_injector_empty_when_not_interrupted() -> None:
    """无打断状态时返回空字符串 (零行为变化)."""
    runtime = ConversationRuntime("a1", "s1")
    injector = InterruptInjector(runtime=runtime)
    result = await injector.build(_make_injection_context())
    assert result == ""


@pytest.mark.asyncio
async def test_interrupt_injector_injects_hint_when_interrupted() -> None:
    """打断后注入"上一轮被新消息打断"内部提示."""
    runtime = ConversationRuntime("a1", "s1", max_interrupts_per_turn=1)
    runtime.request_interrupt(reason="用户发了新消息")
    injector = InterruptInjector(runtime=runtime)
    result = await injector.build(_make_injection_context())
    assert "打断" in result or "被打断" in result
    assert "内部" in result or "参考" in result  # 注入为内部参考, 不直接告诉用户


@pytest.mark.asyncio
async def test_interrupt_injector_clears_after_injection() -> None:
    """注入后清空 interrupt_state, 避免下一轮重复注入."""
    runtime = ConversationRuntime("a1", "s1", max_interrupts_per_turn=1)
    runtime.request_interrupt()
    injector = InterruptInjector(runtime=runtime)
    first = await injector.build(_make_injection_context())
    assert first != ""
    # 注入后状态应已清空, 再次 build 返回空
    second = await injector.build(_make_injection_context())
    assert second == ""


# ── 默认零行为变化 ───────────────────────────────────────────────


def test_runtime_default_max_interrupts_per_turn_is_one() -> None:
    """默认 max_interrupts_per_turn=1 (保守)."""
    runtime = ConversationRuntime("a1", "s1")
    assert runtime.max_interrupts_per_turn == 1
