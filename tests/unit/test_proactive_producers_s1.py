"""S1 主动任务生产者真实产出逻辑单测。

骨架单测 (test_proactive_producers_scaffolding.py) 验证 default-off / memory=None 时
恒返回 []; 本文件验证 S1 激活后三个 Producer 的真实产出路径 + 去重 + _build_task_producer
注入 memory 的接线。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from isac.channel.model import ISACMessage
from isac.runtime.conversation.producer import (
    DateReminderProducer,
    MemoryAssociationProducer,
    TopicFollowupProducer,
)
from isac.runtime.conversation.registry import ConversationRuntimeRegistry
from isac.runtime.conversation.runtime import ConversationRuntime


@dataclass
class _FakeHit:
    id: str
    content: str
    score: float


class _FakeMemory:
    """记录调用参数 + 返回预设 hit 列表。"""

    def __init__(self, hits: list[_FakeHit]) -> None:
        self._hits = hits
        self.calls: list[dict] = []

    async def search(self, query: str, top_k: int = 5, *, user_id: str = "", group_id: str = "") -> list[_FakeHit]:
        self.calls.append({"query": query, "top_k": top_k, "user_id": user_id, "group_id": group_id})
        return list(self._hits)


def _make_runtime_with_message(content: str, *, user_id: str = "u1", group_id: str = "") -> ConversationRuntime:
    """构造带消息缓存的 ConversationRuntime (取末条消息的 user_id/group_id 做 ACL 锚点)。"""
    runtime = ConversationRuntime(agent_id="a1", session_id="s1")
    msg = ISACMessage(
        msg_id="m1", platform="qq", timestamp=0, user_id=user_id, user_name="x",
        group_id=group_id or None, content=content,
    )
    runtime.message_cache.append(msg)
    runtime.last_message_received_at = 1000.0
    return runtime


class _FakeRegistry:
    """仿 ConversationRuntimeRegistry.active_runtimes() 的最小 stub。"""

    def __init__(self, runtimes: list[tuple[str, ConversationRuntime]]) -> None:
        self._runtimes = runtimes

    def active_runtimes(self) -> list[tuple[str, ConversationRuntime]]:
        return list(self._runtimes)


# ── DateReminderProducer ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_date_reminder_produces_when_in_trigger_window() -> None:
    """命中含'生日'+日期关键词且在触发窗口内 → 产出 intent=date_reminder。"""
    # 3 月 5 日附近
    import time as _time

    fake_now = _time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, 0))  # 2026-03-05 12:00
    hits = [_FakeHit(id="h1", content="我生日是3月5日", score=1.0)]
    memory = _FakeMemory(hits)
    runtime = _make_runtime_with_message("聊聊天", user_id="u1")
    producer = DateReminderProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), memory=memory,
    )
    tasks = await producer(fake_now)
    assert len(tasks) == 1
    assert tasks[0].intent == "date_reminder"
    assert tasks[0].source == "memory"
    # ACL 锚点: 用末条消息的 user_id
    assert memory.calls[0]["user_id"] == "u1"


@pytest.mark.asyncio
async def test_date_reminder_dedup_same_year() -> None:
    """同一年同一天再次调用 → 因去重不重复产出。"""
    import time as _time

    fake_now = _time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, 0))
    hits = [_FakeHit(id="h1", content="我生日是3月5日", score=1.0)]
    memory = _FakeMemory(hits)
    runtime = _make_runtime_with_message("hi", user_id="u1")
    producer = DateReminderProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), memory=memory,
    )
    assert len(await producer(fake_now)) == 1
    assert len(await producer(fake_now)) == 0  # 同年同日已提醒过


@pytest.mark.asyncio
async def test_date_reminder_skips_non_relevant_content() -> None:
    """命中含日期但无日期关键词 (生日/纪念日/周年) → 不产出。"""
    import time as _time

    fake_now = _time.mktime((2026, 3, 5, 12, 0, 0, 0, 0, 0))
    hits = [_FakeHit(id="h1", content="今天3月5日", score=1.0)]  # 无关键词
    memory = _FakeMemory(hits)
    runtime = _make_runtime_with_message("hi", user_id="u1")
    producer = DateReminderProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), memory=memory,
    )
    assert await producer(fake_now) == []


@pytest.mark.asyncio
async def test_date_reminder_no_memory_returns_empty() -> None:
    """memory=None 恒返回 [] (零行为变化基线)。"""
    producer = DateReminderProducer(agent_id="a1", registry=_FakeRegistry([]))
    assert await producer(1000.0) == []


# ── TopicFollowupProducer ────────────────────────────────────────


@pytest.mark.asyncio
async def test_topic_followup_produces_after_cooldown() -> None:
    """末条消息含'提醒我' + 已静默超冷却窗口 → 产出。"""
    runtime = _make_runtime_with_message("提醒我晚点给你看", user_id="u1")
    producer = TopicFollowupProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), followup_idle_seconds=60.0,
    )
    # last_message_received_at=1000, now=2000 → 静默 1000s > 60s
    tasks = await producer(2000.0)
    assert len(tasks) == 1
    assert tasks[0].intent == "topic_followup"


@pytest.mark.asyncio
async def test_topic_followup_skips_within_cooldown() -> None:
    """末条消息含延后型短语但静默未超冷却窗口 → 不产出。"""
    runtime = _make_runtime_with_message("提醒我晚点", user_id="u1")
    producer = TopicFollowupProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), followup_idle_seconds=60.0,
    )
    # now=1020 → 静默 20s < 60s
    assert await producer(1020.0) == []


@pytest.mark.asyncio
async def test_topic_followup_skips_non_unfinished_message() -> None:
    """末条消息既无延后型短语也不问号结尾 → 不产出。"""
    runtime = _make_runtime_with_message("好的没问题", user_id="u1")
    producer = TopicFollowupProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), followup_idle_seconds=60.0,
    )
    assert await producer(2000.0) == []


@pytest.mark.asyncio
async def test_topic_followup_question_tail_triggers() -> None:
    """问号结尾的提问 + 静默超窗口 → 产出。"""
    runtime = _make_runtime_with_message("这个怎么用？", user_id="u1")
    producer = TopicFollowupProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), followup_idle_seconds=60.0,
    )
    assert len(await producer(2000.0)) == 1


@pytest.mark.asyncio
async def test_topic_followup_dedup_within_same_window() -> None:
    """同一静默窗口内再次调用 → 因去重不重复产出。"""
    runtime = _make_runtime_with_message("提醒我晚点", user_id="u1")
    producer = TopicFollowupProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), followup_idle_seconds=60.0,
    )
    assert len(await producer(2000.0)) == 1
    assert await producer(2000.0) == []  # 同窗口已跟进过


@pytest.mark.asyncio
async def test_topic_followup_re_arms_after_new_message() -> None:
    """新消息到达后重新武装 (last_message_received_at 前进)。"""
    runtime = _make_runtime_with_message("提醒我晚点", user_id="u1")
    producer = TopicFollowupProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), followup_idle_seconds=60.0,
    )
    assert len(await producer(2000.0)) == 1  # 首次产出
    # 用户又发了新消息 → last_message_received_at 前进; 仍是未闭合话题
    runtime.message_cache.append(
        ISACMessage(msg_id="m2", platform="qq", timestamp=0, user_id="u1", user_name="x", content="提醒我晚点")
    )
    runtime.last_message_received_at = 2100.0
    assert len(await producer(2200.0)) == 1  # 重新武装, 再次产出


# ── MemoryAssociationProducer ────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_association_produces_above_threshold() -> None:
    """score 超阈值 → 产出 intent=memory_association。"""
    hits = [_FakeHit(id="h1", content="相关历史记忆内容", score=0.5)]
    memory = _FakeMemory(hits)
    runtime = _make_runtime_with_message("最近怎么样", user_id="u1")
    producer = MemoryAssociationProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), memory=memory, min_score=0.15,
    )
    tasks = await producer(1000.0)
    assert len(tasks) == 1
    assert tasks[0].intent == "memory_association"
    assert "相关历史记忆内容" in tasks[0].reason


@pytest.mark.asyncio
async def test_memory_association_skips_below_threshold() -> None:
    """score 不足阈值 → 不产出。"""
    hits = [_FakeHit(id="h1", content="无关内容", score=0.05)]
    memory = _FakeMemory(hits)
    runtime = _make_runtime_with_message("hi", user_id="u1")
    producer = MemoryAssociationProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), memory=memory, min_score=0.15,
    )
    assert await producer(1000.0) == []


@pytest.mark.asyncio
async def test_memory_association_dedup_recent_hit() -> None:
    """同一 hit.id 短期内不重复产出。"""
    hits = [_FakeHit(id="h1", content="某条历史记忆", score=0.5)]
    memory = _FakeMemory(hits)
    runtime = _make_runtime_with_message("hi", user_id="u1")
    producer = MemoryAssociationProducer(
        agent_id="a1", registry=_FakeRegistry([("s1", runtime)]), memory=memory, min_score=0.15,
    )
    assert len(await producer(1000.0)) == 1
    assert await producer(1000.0) == []  # 同 hit.id 已产出过


@pytest.mark.asyncio
async def test_memory_association_no_memory_returns_empty() -> None:
    """memory=None 恒返回 [] (零行为变化基线)。"""
    producer = MemoryAssociationProducer(agent_id="a1", registry=_FakeRegistry([]))
    assert await producer(1000.0) == []


# ── _build_task_producer 注入 memory ─────────────────────────────


def test_build_task_producer_injects_memory_to_date_reminder() -> None:
    """_build_task_producer 传 memory 后 DateReminderProducer 持有同一 memory 实例。"""
    from isac.runtime.assembly import _build_task_producer
    from isac.runtime.config import AgentConfig

    config = AgentConfig(agent_id="a1")
    proactive_cfg = {"date_reminder_enabled": True}
    registry = ConversationRuntimeRegistry()
    memory = _FakeMemory([])
    producer = _build_task_producer(config, proactive_cfg, registry, memory=memory)
    assert producer is not None
    # DateReminderProducer 是单个 producer (非 Composite)
    assert isinstance(producer, DateReminderProducer)
    assert producer._memory is memory  # noqa: SLF001


def test_build_task_producer_injects_memory_to_all_three() -> None:
    """三个生产者全开 → CompositeTaskProducer, 各自持有同一 memory。"""
    from isac.runtime.assembly import _build_task_producer
    from isac.runtime.config import AgentConfig

    config = AgentConfig(agent_id="a1")
    proactive_cfg = {
        "date_reminder_enabled": True,
        "topic_followup_enabled": True,
        "memory_association_enabled": True,
    }
    registry = ConversationRuntimeRegistry()
    memory = _FakeMemory([])
    producer = _build_task_producer(config, proactive_cfg, registry, memory=memory)
    assert producer is not None
    # 三个生产者全开 → CompositeTaskProducer
    from isac.runtime.conversation.producer import CompositeTaskProducer
    assert isinstance(producer, CompositeTaskProducer)
    inner = producer._producers  # noqa: SLF001
    assert len(inner) == 3
    for p in inner:
        assert p._memory is memory  # noqa: SLF001
