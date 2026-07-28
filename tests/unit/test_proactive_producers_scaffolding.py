"""主动任务生产者骨架单测 (S1, TODO(proactive-ext))。

验证新增 3 个生产者 (DateReminder / TopicFollowup / MemoryAssociation) 骨架 ``__call__``
恒返回 [] (零产出、零行为变化), 以及 CompositeTaskProducer 汇总多个生产者输出并隔离
单个生产者异常。骨架阶段不触发任何主动任务, 主链路行为不变。
"""

from __future__ import annotations

from isac.runtime.conversation.models import ProactiveTask
from isac.runtime.conversation.producer import (
    CompositeTaskProducer,
    DateReminderProducer,
    MemoryAssociationProducer,
    TopicFollowupProducer,
)
from isac.runtime.conversation.registry import ConversationRuntimeRegistry


def _make_task(tid: str) -> ProactiveTask:
    return ProactiveTask(
        task_id=tid, agent_id="a1", session_id="s1", source="memory", intent="i", reason="r"
    )


def test_date_reminder_producer_skeleton_returns_empty() -> None:
    """memory=None 时骨架恒返回 []。"""
    producer = DateReminderProducer(agent_id="a1", registry=ConversationRuntimeRegistry())
    # S1: __call__ 改为 async (memory.search await), 用 asyncio.run 驱动
    import asyncio
    assert asyncio.run(producer(1000.0)) == []


def test_topic_followup_producer_skeleton_returns_empty() -> None:
    producer = TopicFollowupProducer(agent_id="a1", registry=ConversationRuntimeRegistry())
    import asyncio
    assert asyncio.run(producer(1000.0)) == []


def test_memory_association_producer_skeleton_returns_empty() -> None:
    producer = MemoryAssociationProducer(agent_id="a1", registry=ConversationRuntimeRegistry())
    import asyncio
    assert asyncio.run(producer(1000.0)) == []


def test_composite_aggregates_in_order() -> None:
    async def p1(now: float) -> list[ProactiveTask]:
        return [_make_task("t1")]

    async def p2(now: float) -> list[ProactiveTask]:
        return [_make_task("t2"), _make_task("t3")]

    composite = CompositeTaskProducer([p1, p2])
    import asyncio
    assert [t.task_id for t in asyncio.run(composite(1000.0))] == ["t1", "t2", "t3"]


def test_composite_isolates_failing_producer() -> None:
    async def boom(now: float) -> list[ProactiveTask]:
        raise RuntimeError("boom")

    async def ok(now: float) -> list[ProactiveTask]:
        return [_make_task("ok")]

    composite = CompositeTaskProducer([boom, ok])
    import asyncio
    assert [t.task_id for t in asyncio.run(composite(1000.0))] == ["ok"]


def test_composite_empty_returns_empty() -> None:
    composite = CompositeTaskProducer([])
    import asyncio
    assert asyncio.run(composite(1000.0)) == []
