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
    ForcedTurnState,
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
