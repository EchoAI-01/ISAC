"""ConversationRuntime L2-L5 骨架测试。

验证 L2 (debounce/WaitEndReason/TriggerSource)、L3 (ProactiveScheduler)、
L4 (InterruptState)、L5 (ConversationStateStore) 的契约与骨架安全行为,
且默认关闭时对主链路零行为变化。真实 debounce 循环/主动调度/打断/恢复属
实现节点 (L2-L5), 本文件只覆盖骨架级行为。
"""

from __future__ import annotations

from isac.runtime.conversation import (
    ConversationSnapshot,
    ConversationStateStore,
    DebounceWindow,
    ForcedTurnState,
    InterruptState,
    ProactiveScheduler,
    ProactiveTask,
    ProactiveTaskQueue,
    TriggerSource,
    WaitEndReason,
    WaitState,
)

# ── L2: 枚举 + WaitState.end_reason + DebounceWindow ──────────────


def test_trigger_source_and_wait_end_reason_values() -> None:
    assert TriggerSource.PROACTIVE.value == "proactive"
    assert set(TriggerSource) >= {TriggerSource.MESSAGE, TriggerSource.TIMEOUT, TriggerSource.HANDOFF}
    assert WaitEndReason.TIMEOUT.value == "timeout"
    assert set(WaitEndReason) == {WaitEndReason.MESSAGE, WaitEndReason.TIMEOUT, WaitEndReason.PROACTIVE}


def test_wait_state_end_reason_defaults_none_and_is_settable() -> None:
    wait = WaitState(tool_call_id="c1", started_at=1.0)
    assert wait.end_reason is None  # 尾部默认字段, 不破坏既有关键字构造
    wait.end_reason = WaitEndReason.MESSAGE
    assert wait.end_reason is WaitEndReason.MESSAGE


def test_debounce_window_zero_is_always_settled() -> None:
    # debounce<=0 退化为不去抖 (每条立即可触发), 与现有行为一致
    win = DebounceWindow(debounce_seconds=0.0)
    win.touch(now=100.0)
    assert win.is_settled(now=100.0) is True


def test_debounce_window_positive_respects_silence_window() -> None:
    win = DebounceWindow(debounce_seconds=5.0)
    win.touch(now=100.0)
    assert win.is_settled(now=103.0) is False  # 窗口内
    assert win.is_settled(now=105.0) is True  # 窗口已过


# ── L3: ProactiveScheduler ──────────────────────────────────────


def _task(**kw: str) -> ProactiveTask:
    base = {"task_id": "t1", "agent_id": "a1", "session_id": "s1", "source": "memory", "intent": "i", "reason": "r"}
    base.update(kw)
    return ProactiveTask(**base)  # type: ignore[arg-type]


def test_scheduler_may_fire_respects_cooldown() -> None:
    sched = ProactiveScheduler(min_interval_seconds=0.0)
    assert sched.may_fire(now=100.0) is True  # 无冷却
    sched2 = ProactiveScheduler(min_interval_seconds=10.0)
    assert sched2.may_fire(now=5.0) is False  # _last_fired_at=0, 未过冷却


def test_scheduler_authorize_requires_source_intent_reason() -> None:
    sched = ProactiveScheduler()
    assert sched.authorize(_task()) is True
    assert sched.authorize(_task(source="", intent="", reason="")) is False


def test_scheduler_to_forced_turn_marks_proactive() -> None:
    sched = ProactiveScheduler()
    forced = sched.to_forced_turn(_task(reason="生日提醒"))
    assert isinstance(forced, ForcedTurnState)
    assert forced.source == TriggerSource.PROACTIVE.value
    assert forced.reason == "生日提醒"


def test_scheduler_defaults_own_queue() -> None:
    q = ProactiveTaskQueue()
    sched = ProactiveScheduler(queue=q)
    assert sched.queue is q
    assert isinstance(ProactiveScheduler().queue, ProactiveTaskQueue)


# ── L4: InterruptState ──────────────────────────────────────────


def test_interrupt_state_defaults() -> None:
    st = InterruptState()
    assert st.interrupt_count == 0
    assert st.superseded is False
    assert st.reason == ""


# ── L5: ConversationStateStore ──────────────────────────────────


def test_state_store_save_then_load_returns_snapshot() -> None:
    """L5 已实现: save 落盘 + load 读回 (而非 no-op). 用 tmp 目录避免污染 data/."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStateStore(base_dir=tmp)
        snap = ConversationSnapshot(agent_id="a1", session_id="s1")
        store.save(snap)  # L5: 真实落盘, 不抛
        loaded = store.load("a1", "s1")  # L5: 真实读回, 短间隔内恢复
        assert loaded is not None
        assert loaded.state == "idle"  # 复位运行态
        # 默认 base_dir 下不存在的 session: load 返回 None (新会话)
        assert store.load("a1", "nonexistent") is None


def test_conversation_snapshot_defaults() -> None:
    snap = ConversationSnapshot(agent_id="a1", session_id="s1")
    assert snap.state == "idle"
    assert snap.pending_wait is None
    assert snap.recent_message_ids == []
    assert snap.recovery_hint == ""


# ── 默认关闭时主链路零行为变化 (复验) ────────────────────────────


def test_manager_conversation_still_disabled_by_default() -> None:
    from isac.runtime.manager import AgentManager

    assert AgentManager({"global_config": {}})._conversation_enabled() is False
