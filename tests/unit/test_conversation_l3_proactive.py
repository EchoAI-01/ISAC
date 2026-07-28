"""L3 主动任务调度业务测试。

覆盖:
- ProactiveTaskQueue 按 priority 排序 (high > normal > low; 同优先 FIFO)
- ProactiveScheduler.authorize 真实校验 (allowed_sources + source/intent/reason 非空)
- ProactiveScheduler.to_forced_turn 触发时更新 _last_fired_at
- ProactiveScheduler.start/stop 后台循环: poll + authorize + may_fire + 唤醒 callback
- enabled=False 主链路零行为变化
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from isac.runtime.conversation import (
    ConversationRuntimeRegistry,
    ForcedTurnState,
    IdleReengageProducer,
    ProactiveScheduler,
    ProactiveTask,
    ProactiveTaskQueue,
    TriggerSource,
)


def _task(task_id: str = "t1", priority: str = "normal", **kw: str) -> ProactiveTask:
    base: dict[str, Any] = {
        "task_id": task_id,
        "agent_id": "a1",
        "session_id": "s1",
        "source": "memory",
        "intent": "i",
        "reason": "r",
        "priority": priority,
    }
    base.update(kw)
    return ProactiveTask(**base)  # type: ignore[arg-type]


# ── ProactiveTaskQueue priority 排序 ──────────────────────────────


def test_queue_enqueue_poll_orders_by_priority() -> None:
    q = ProactiveTaskQueue()
    q.enqueue(_task("t1", priority="low"))
    q.enqueue(_task("t2", priority="high"))
    q.enqueue(_task("t3", priority="normal"))
    order = [q.poll().task_id, q.poll().task_id, q.poll().task_id]  # type: ignore[union-attr]
    assert order == ["t2", "t3", "t1"]  # high → normal → low


def test_queue_enqueue_same_priority_keeps_fifo() -> None:
    q = ProactiveTaskQueue()
    q.enqueue(_task("t1", priority="normal"))
    q.enqueue(_task("t2", priority="normal"))
    q.enqueue(_task("t3", priority="normal"))
    order = [q.poll().task_id, q.poll().task_id, q.poll().task_id]  # type: ignore[union-attr]
    assert order == ["t1", "t2", "t3"]


def test_queue_poll_empty_returns_none() -> None:
    assert ProactiveTaskQueue().poll() is None


def test_queue_enqueue_returns_true_when_under_capacity() -> None:
    q = ProactiveTaskQueue(max_size=2)
    assert q.enqueue(_task("t1")) is True
    assert len(q) == 1


def test_queue_enqueue_rejects_when_at_capacity() -> None:
    """CR2-Fix-5: 队列无容量上限时任何来源可无限入队。超过 max_size 拒绝新任务,
    队列长度不变, enqueue 返回 False 供调用方感知。"""
    q = ProactiveTaskQueue(max_size=2)
    assert q.enqueue(_task("t1")) is True
    assert q.enqueue(_task("t2")) is True
    assert q.enqueue(_task("t3")) is False
    assert len(q) == 2
    assert q.poll().task_id == "t1"  # type: ignore[union-attr]


# ── ProactiveScheduler.authorize ──────────────────────────────────


def test_scheduler_authorize_rejects_disallowed_source() -> None:
    sched = ProactiveScheduler(allowed_sources={"memory", "schedule"})
    assert sched.authorize(_task(source="memory")) is True
    assert sched.authorize(_task(source="plugin")) is False  # 不在 allowed_sources


def test_scheduler_authorize_rejects_empty_fields() -> None:
    sched = ProactiveScheduler()
    assert sched.authorize(_task(source="", intent="", reason="")) is False


def test_scheduler_default_allowed_sources_allows_known_sources() -> None:
    sched = ProactiveScheduler()  # 默认 allowed_sources = 全部已知来源
    for s in ("plugin", "memory", "schedule", "agent", "api"):
        assert sched.authorize(_task(source=s)) is True


def test_scheduler_authorize_rejects_forged_source_without_matching_token() -> None:
    """CR2-Fix-7: authorize() 此前只是字符串白名单, 任何能构造
    ProactiveTask(source="plugin", ...) 的代码都能通过鉴权, 没有身份/签名校验。
    配置了 source_tokens 后, 该 source 的任务必须带匹配的 caller_token。"""
    sched = ProactiveScheduler(source_tokens={"plugin": "real-secret"})
    # 持有正确 token 的合法调用方通过
    assert sched.authorize(_task(source="plugin", caller_token="real-secret")) is True
    # 伪造 source 但不持有正确 token 的调用方被拒绝
    assert sched.authorize(_task(source="plugin", caller_token="forged")) is False
    assert sched.authorize(_task(source="plugin", caller_token="")) is False


def test_scheduler_authorize_skips_token_check_for_unconfigured_source() -> None:
    """未在 source_tokens 中配置 token 的 source 保持现状白名单行为 (向后兼容)。"""
    sched = ProactiveScheduler(source_tokens={"plugin": "real-secret"})
    assert sched.authorize(_task(source="memory", caller_token="")) is True


# ── ProactiveScheduler.to_forced_turn ─────────────────────────────


def test_scheduler_to_forced_turn_marks_proactive_and_records_time() -> None:
    sched = ProactiveScheduler()
    forced = sched.to_forced_turn(_task(reason="生日提醒"), now=100.0)
    assert isinstance(forced, ForcedTurnState)
    assert forced.source == TriggerSource.PROACTIVE.value
    assert forced.reason == "生日提醒"
    # 触发后按 session_id 记录的 _last_fired_at 已更新 (供下次 may_fire 判定)
    assert sched._last_fired_at["s1"] == 100.0  # noqa: SLF001


def test_scheduler_may_fire_cooldown_is_isolated_per_session() -> None:
    """CR2-Fix-6: 冷却此前是调度器级单一时间戳, 一个高频会话触发的主动任务会
    占用整个 Agent 唯一的冷却窗口, 饿死其他会话的合法主动提醒。应按 session_id
    隔离冷却状态。"""
    sched = ProactiveScheduler(min_interval_seconds=10.0)
    sched.to_forced_turn(_task(session_id="s1"), now=100.0)
    # s1 刚触发过, 在冷却窗口内
    assert sched.may_fire(105.0, session_id="s1") is False
    # s2 从未触发过, 不受 s1 的冷却影响
    assert sched.may_fire(105.0, session_id="s2") is True


# ── ProactiveScheduler.start/stop 后台循环 ────────────────────────


@pytest.mark.asyncio
async def test_scheduler_start_polls_and_invokes_wake_callback() -> None:
    """start() 后台循环 poll queue → authorize → may_fire → wake_callback."""
    sched = ProactiveScheduler(min_interval_seconds=0.0, poll_interval_seconds=0.02)
    q = sched.queue
    q.enqueue(_task(task_id="t1", reason="提醒用户喝水"))
    fired: list[ProactiveTask] = []

    async def wake(task: ProactiveTask) -> None:
        fired.append(task)

    await sched.start(wake_callback=wake)
    await asyncio.sleep(0.1)
    await sched.stop()
    assert len(fired) == 1
    assert fired[0].task_id == "t1"
    assert fired[0].reason == "提醒用户喝水"


@pytest.mark.asyncio
async def test_scheduler_start_skips_unauthorized_task() -> None:
    """未通过 authorize 的任务被跳过 (不调 wake_callback, 不阻塞队列)."""
    sched = ProactiveScheduler(allowed_sources={"memory"}, poll_interval_seconds=0.02)
    sched.queue.enqueue(_task(task_id="t1", source="plugin"))  # plugin 不在 allowed
    fired: list[ProactiveTask] = []

    async def wake(task: ProactiveTask) -> None:
        fired.append(task)

    await sched.start(wake_callback=wake)
    await asyncio.sleep(0.1)
    await sched.stop()
    assert fired == []  # 被跳过
    assert len(sched.queue) == 0  # 任务已出队 (不阻塞)


@pytest.mark.asyncio
async def test_scheduler_start_skips_when_within_cooldown() -> None:
    """冷却窗口内 may_fire=False, 任务退回队列头部等下次轮询."""
    import time as _time

    sched = ProactiveScheduler(min_interval_seconds=10.0, poll_interval_seconds=0.02)
    # 模拟"刚触发过一次": s1 的 _last_fired_at 设为当前时间, 此时 may_fire 应 False
    sched._last_fired_at["s1"] = _time.time()  # noqa: SLF001
    sched.queue.enqueue(_task(task_id="t1"))
    fired: list[ProactiveTask] = []

    async def wake(task: ProactiveTask) -> None:
        fired.append(task)

    await sched.start(wake_callback=wake)
    await asyncio.sleep(0.1)
    await sched.stop()
    assert fired == []
    assert len(sched.queue) == 1  # 任务仍在队列中, 等冷却过去


@pytest.mark.asyncio
async def test_scheduler_start_empty_queue_does_nothing() -> None:
    """空队列不调 wake_callback, 循环继续运转."""
    sched = ProactiveScheduler(poll_interval_seconds=0.02)
    fired: list[ProactiveTask] = []

    async def wake(task: ProactiveTask) -> None:
        fired.append(task)

    await sched.start(wake_callback=wake)
    await asyncio.sleep(0.1)
    await sched.stop()
    assert fired == []


@pytest.mark.asyncio
async def test_scheduler_stop_cancels_loop_cleanly() -> None:
    """stop() 取消后台 task, 不留 dangling task."""
    sched = ProactiveScheduler(poll_interval_seconds=0.02)
    await sched.start(wake_callback=None)
    await sched.stop()
    # 重复 stop 不抛
    await sched.stop()
    # 队列空, 后台 task 已完成
    assert sched._loop_task is None or sched._loop_task.done()  # noqa: SLF001


# ── 默认零行为变化 ───────────────────────────────────────────────


def test_scheduler_default_no_background_loop_until_started() -> None:
    """scheduler 构造后不启动后台循环 (零行为变化)."""
    sched = ProactiveScheduler()
    assert sched._loop_task is None  # noqa: SLF001


# ── R2-2: IdleReengageProducer (主动任务的真实生产者) ──────────────


def _registry_with_session(session_id: str = "s1", last_activity: float = 100.0) -> ConversationRuntimeRegistry:
    registry = ConversationRuntimeRegistry()
    registry.get("a1", session_id).last_message_received_at = last_activity
    return registry


@pytest.mark.asyncio
async def test_idle_producer_yields_task_for_idle_session() -> None:
    """会话静默超过 idle_seconds → 产出一个 source=schedule 的 re-engage 任务。"""
    producer = IdleReengageProducer(agent_id="a1", registry=_registry_with_session("s1", 100.0), idle_seconds=60.0)
    tasks = await producer(now=200.0)  # 静默 100s > 60s
    assert len(tasks) == 1
    task = tasks[0]
    assert task.agent_id == "a1"
    assert task.session_id == "s1"
    assert task.source == "schedule"
    assert task.intent and task.reason  # authorize 要求非空


@pytest.mark.asyncio
async def test_idle_producer_skips_recently_active_session() -> None:
    producer = IdleReengageProducer(agent_id="a1", registry=_registry_with_session("s1", 180.0), idle_seconds=60.0)
    assert await producer(now=200.0) == []  # 仅静默 20s < 60s


@pytest.mark.asyncio
async def test_idle_producer_skips_never_messaged_session() -> None:
    """从未收到消息的会话 (last_message_received_at=0) 不主动打扰。"""
    registry = ConversationRuntimeRegistry()
    registry.get("a1", "s1")  # last_message_received_at 默认 0.0
    producer = IdleReengageProducer(agent_id="a1", registry=registry, idle_seconds=60.0)
    assert await producer(now=200.0) == []


@pytest.mark.asyncio
async def test_idle_producer_dedups_until_new_activity() -> None:
    """同一静默窗口只 re-engage 一次 (防刷屏); 新用户消息到达后重新武装。"""
    registry = _registry_with_session("s1", 100.0)
    producer = IdleReengageProducer(agent_id="a1", registry=registry, idle_seconds=60.0)
    assert len(await producer(now=200.0)) == 1  # 首次
    assert await producer(now=260.0) == []  # 同窗口不重复
    registry.get("a1", "s1").last_message_received_at = 300.0  # 新消息
    assert len(await producer(now=400.0)) == 1  # 新静默窗口再次 re-engage


@pytest.mark.asyncio
async def test_scheduler_with_producer_enqueues_and_fires_idle_reengage() -> None:
    """R2-2: 配置 task_producer 后, 调度循环真实产出并触发主动任务 —— 此前生产侧
    无任何入口 enqueue, 队列恒空, 主动任务功能完全不可达。"""
    import time as _time

    registry = ConversationRuntimeRegistry()
    registry.get("a1", "s1").last_message_received_at = _time.time() - 1000.0  # 早已静默
    producer = IdleReengageProducer(agent_id="a1", registry=registry, idle_seconds=1.0)
    sched = ProactiveScheduler(task_producer=producer, min_interval_seconds=0.0, poll_interval_seconds=0.02)
    fired: list[ProactiveTask] = []

    async def wake(task: ProactiveTask) -> None:
        fired.append(task)

    await sched.start(wake_callback=wake)
    await asyncio.sleep(0.1)
    await sched.stop()
    assert len(fired) == 1  # 生产者入队 + 循环触发, 且去重不刷屏
    assert fired[0].source == "schedule"
    assert fired[0].session_id == "s1"
