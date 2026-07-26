"""ConversationRuntime 框架骨架测试 (L1)。

验证契约、状态机、registry 隔离与上限、主动队列就位, 且默认关闭时对现有主链路
零行为变化。L2 已落地后 enter_wait 为 async、resolve_wait 接 WaitEndReason 枚举。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from isac.runtime.conversation import (
    ConversationRuntime,
    ConversationRuntimeRegistry,
    ConversationState,
    ForcedTurnState,
    ProactiveTask,
    ProactiveTaskQueue,
    WaitEndReason,
    WaitState,
)


def _msg(text: str = "hi") -> SimpleNamespace:
    return SimpleNamespace(content=text)


def test_state_defaults_idle_and_transitions() -> None:
    rt = ConversationRuntime("a1", "s1")
    assert rt.state is ConversationState.IDLE
    rt.transition_to(ConversationState.THINKING)
    assert rt.state is ConversationState.THINKING


def test_register_and_drain_messages() -> None:
    rt = ConversationRuntime("a1", "s1")
    rt.register_message(_msg("m1"))
    rt.register_message(_msg("m2"))
    assert len(rt.message_cache) == 2
    assert len(rt.drain_new_messages()) == 2
    # 再次 drain 无新消息 (last_processed_index 已推进)
    assert rt.drain_new_messages() == []


@pytest.mark.asyncio
async def test_enter_and_resolve_wait() -> None:
    rt = ConversationRuntime("a1", "s1")
    wait = WaitState(tool_call_id="c1", started_at=1.0, requested_seconds=5.0, reason="等回复")
    await rt.enter_wait(wait)
    assert rt.state is ConversationState.WAITING
    assert rt.pending_wait is wait
    resolved = rt.resolve_wait(WaitEndReason.TIMEOUT)
    assert resolved is wait
    assert resolved.end_reason is WaitEndReason.TIMEOUT
    assert rt.pending_wait is None
    assert rt.state is ConversationState.IDLE


def test_request_interrupt_is_safe() -> None:
    ConversationRuntime("a1", "s1").request_interrupt()  # 骨架: 不抛异常即可


def test_registry_isolates_by_agent_and_session() -> None:
    reg = ConversationRuntimeRegistry()
    r1 = reg.get("a1", "s1")
    r2 = reg.get("a1", "s2")
    r3 = reg.get("a2", "s1")
    assert r1 is not r2
    assert r1 is not r3
    assert reg.get("a1", "s1") is r1  # 同 key 复用
    assert len(reg) == 3


def test_registry_enforces_fifo_cap() -> None:
    reg = ConversationRuntimeRegistry(max_runtimes=2)
    reg.get("a", "s1")
    reg.get("a", "s2")
    reg.get("a", "s3")  # 触发淘汰最旧 (s1)
    assert len(reg) == 2


def test_registry_discard() -> None:
    reg = ConversationRuntimeRegistry()
    reg.get("a1", "s1")
    reg.discard("a1", "s1")
    assert len(reg) == 0


def test_proactive_queue_enqueue_poll_fifo() -> None:
    queue = ProactiveTaskQueue()
    assert queue.poll() is None
    t1 = ProactiveTask(task_id="t1", agent_id="a1", session_id="s1", source="memory", intent="i", reason="r")
    t2 = ProactiveTask(task_id="t2", agent_id="a1", session_id="s1", source="schedule", intent="i", reason="r")
    queue.enqueue(t1)
    queue.enqueue(t2)
    assert len(queue) == 2
    assert queue.poll() is t1
    assert queue.poll() is t2
    assert queue.poll() is None


def test_forced_turn_state_fields() -> None:
    forced = ForcedTurnState(source="proactive", reason="生日提醒")
    assert forced.source == "proactive"
    assert forced.reason == "生日提醒"


def test_manager_conversation_disabled_by_default() -> None:
    from isac.runtime.manager import AgentManager

    assert AgentManager({"global_config": {}})._conversation_enabled() is False


def test_manager_conversation_enabled_when_configured() -> None:
    from isac.runtime.manager import AgentManager

    manager = AgentManager({"global_config": {"conversation": {"enabled": True}}})
    assert manager._conversation_enabled() is True
