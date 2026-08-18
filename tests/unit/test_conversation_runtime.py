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


@pytest.mark.asyncio
async def test_registry_fifo_cap_skips_waiting_session() -> None:
    """Fix-32: 淘汰应跳过正处于 WAITING 的会话, 即便它插入顺序最旧;
    改淘汰次旧但非 WAITING 者, 避免把一个进行中的会话腰斩 (message_cache/
    interrupt_state 等状态被静默清空)。"""
    reg = ConversationRuntimeRegistry(max_runtimes=3)
    s1 = reg.get("a", "s1")
    await s1.enter_wait(
        WaitState(tool_call_id="c1", started_at=1.0, requested_seconds=5.0, reason="等回复")
    )
    s2 = reg.get("a", "s2")
    s3 = reg.get("a", "s3")
    assert len(reg) == 3

    reg.get("a", "s4")  # 触发淘汰: s1(WAITING) 应被跳过, 改淘汰次旧的 s2

    assert len(reg) == 3
    assert reg.get("a", "s1") is s1  # WAITING 会话未被淘汰, 仍是原实例
    assert reg.get("a", "s3") is s3  # 未涉及的会话不受影响
    assert reg.get("a", "s2") is not s2  # s2 被淘汰, 再次 get 是全新实例

    s1.resolve_wait(WaitEndReason.TIMEOUT)  # 清理: 取消超时定时器, 避免测试遗留悬挂任务


@pytest.mark.asyncio
async def test_registry_fifo_cap_falls_back_to_oldest_when_all_waiting() -> None:
    """全部会话都在 WAITING 时软上限保护优先于等待保护: 仍必须淘汰一个 (退回
    淘汰最旧者), 否则软上限形同虚设、无界增长的风险重新出现。"""
    reg = ConversationRuntimeRegistry(max_runtimes=2)
    s1 = reg.get("a", "s1")
    await s1.enter_wait(WaitState(tool_call_id="c1", started_at=1.0, requested_seconds=5.0, reason="r1"))
    s2 = reg.get("a", "s2")
    await s2.enter_wait(WaitState(tool_call_id="c2", started_at=1.0, requested_seconds=5.0, reason="r2"))

    reg.get("a", "s3")  # s1/s2 都在 WAITING, 仍必须淘汰一个 (最旧的 s1)

    assert len(reg) == 2
    assert reg.get("a", "s2") is s2  # 次旧的 s2 保留 (WAITING 但非最旧)
    assert reg.get("a", "s1") is not s1  # 最旧的 s1 仍被淘汰 (软上限优先)

    s2.resolve_wait(WaitEndReason.TIMEOUT)  # 清理: 取消超时定时器


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


def test_rewind_processed_lets_successor_turn_reclaim_interrupted_burst() -> None:
    """Fix-57: 被打断回合的输入回拨 drain 指针后, 接替回合能重新取到。

    场景: 回合 A drain 走 [m1] 进 Loop 后被打断 (回复抑制/不写记忆); 若指针
    不回拨, 接替回合 (触发打断的 m2) drain 只拿到 [m2], m1 三方皆失。回拨后
    接替回合合并处理 [m1, m2]。
    """
    rt = ConversationRuntime("a1", "s1")
    rt.register_message(_msg("m1"))
    burst_a = rt.drain_new_messages()
    assert [m.content for m in burst_a] == ["m1"]
    # 回合 A 被打断 → manager 回拨本回合输入
    rt.rewind_processed(len(burst_a))
    # 触发打断的新消息 m2 到达
    rt.register_message(_msg("m2"))
    burst_b = rt.drain_new_messages()
    assert [m.content for m in burst_b] == ["m1", "m2"]  # m1 被接替回合合并处理


def test_rewind_processed_floor_at_zero_and_noop_for_nonpositive() -> None:
    """Fix-57 边界: 回拨不下穿 0; 0/负数无操作。"""
    rt = ConversationRuntime("a1", "s1")
    rt.register_message(_msg("m1"))
    rt.drain_new_messages()
    rt.rewind_processed(5)  # 超出已处理数量
    assert rt.last_processed_index == 0
    rt.rewind_processed(0)
    rt.rewind_processed(-3)
    assert rt.last_processed_index == 0
