"""J1 UsageStore 存储层测试: schema 迁移、批量落库、事件分页查询。

聚合查询 (aggregate) 单独在实现该功能的提交里补测试, 本文件覆盖 schema/insert_many/
list_events 这三块。
"""

from __future__ import annotations

import time

import pytest

from isac.core.types import TokenUsage
from isac.observability.usage.models import ModelUsageEvent
from isac.observability.usage.storage import UsageStore


def _event(**kw) -> ModelUsageEvent:
    base: dict = dict(
        event_id=f"e-{kw.get('_seq', 1)}",
        trace_id="",
        request_id="",
        agent_id="a1",
        session_id="s1",
        provider="P",
        model="m",
        modality="text",
        operation="chat",
        created_at=int(time.time()),
    )
    kw.pop("_seq", None)
    base.update(kw)
    return ModelUsageEvent(**base)


async def _table_columns(store: UsageStore) -> set[str]:
    assert store._db is not None
    cursor = await store._db.execute("PRAGMA table_info(model_usage_events)")
    return {row[1] for row in await cursor.fetchall()}


@pytest.mark.asyncio
async def test_start_creates_schema_with_detail_token_columns(tmp_path) -> None:
    """J1: 新库一次到位, 应包含 cache/reasoning/audio 明细列。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        columns = await _table_columns(store)
        for column in (
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "audio_input_tokens",
            "audio_output_tokens",
        ):
            assert column in columns
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_start_migrates_old_db_missing_detail_columns(tmp_path) -> None:
    """J1: 旧库 (无明细列) 重新 start() 后应自动补齐, 不丢已有数据。"""
    import aiosqlite

    db_path = tmp_path / "usage.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            """
            CREATE TABLE model_usage_events (
                event_id TEXT PRIMARY KEY, trace_id TEXT, request_id TEXT,
                agent_id TEXT, session_id TEXT, provider TEXT, model TEXT,
                modality TEXT, operation TEXT, prompt_tokens INTEGER,
                completion_tokens INTEGER, total_tokens INTEGER,
                input_units REAL, output_units REAL, unit_name TEXT,
                estimated_cost TEXT, currency TEXT, pricing_version TEXT,
                latency_ms INTEGER, status TEXT, fallback_from TEXT, created_at INTEGER
            )
            """
        )
        await db.execute(
            "INSERT INTO model_usage_events (event_id, provider, model, created_at) VALUES (?,?,?,?)",
            ("old-event", "P", "m", 1000),
        )
        await db.commit()

    store = UsageStore(str(db_path))
    await store.start()
    try:
        columns = await _table_columns(store)
        assert "cache_read_tokens" in columns
        # 旧数据仍在, 迁移没有丢数据
        events = await store.list_events(limit=10)
        assert any(row["event_id"] == "old-event" for row in events)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_insert_many_writes_all_events_in_one_batch(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        events = [_event(_seq=i, event_id=f"e{i}") for i in range(3)]
        await store.insert_many(events)
        rows = await store.list_events(limit=10)
        assert {row["event_id"] for row in rows} == {"e0", "e1", "e2"}
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_insert_many_persists_detail_token_columns(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [_event(usage=TokenUsage(prompt_tokens=100, cache_read_tokens=80, reasoning_tokens=20))]
        )
        rows = await store.list_events(limit=10)
        assert rows[0]["cache_read_tokens"] == 80
        assert rows[0]["reasoning_tokens"] == 20
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_insert_many_noop_when_not_started(tmp_path) -> None:
    """未 start 时静默跳过, 不抛异常 (惰性, 不阻塞主调用)。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.insert_many([_event()])  # 不抛异常即通过


@pytest.mark.asyncio
async def test_insert_still_works_as_single_event_shorthand(tmp_path) -> None:
    """insert() 保留, 内部委托 insert_many([event]), 兼容既有调用点。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert(_event(event_id="solo"))
        rows = await store.list_events(limit=10)
        assert rows[0]["event_id"] == "solo"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_events_orders_by_created_at_desc(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="old", created_at=100),
                _event(event_id="new", created_at=200),
            ]
        )
        rows = await store.list_events(limit=10)
        assert [row["event_id"] for row in rows] == ["new", "old"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_events_filters_by_agent_id(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="a", agent_id="agent-a"),
                _event(event_id="b", agent_id="agent-b"),
            ]
        )
        rows = await store.list_events(filters={"agent_id": "agent-a"}, limit=10)
        assert [row["event_id"] for row in rows] == ["a"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_events_filters_by_time_range(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="early", created_at=100),
                _event(event_id="mid", created_at=200),
                _event(event_id="late", created_at=300),
            ]
        )
        rows = await store.list_events(filters={"from_ts": 150, "to_ts": 250}, limit=10)
        assert [row["event_id"] for row in rows] == ["mid"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_events_respects_limit_and_offset(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many([_event(event_id=f"e{i}", created_at=i) for i in range(5)])
        page1 = await store.list_events(limit=2, offset=0)
        page2 = await store.list_events(limit=2, offset=2)
        assert [row["event_id"] for row in page1] == ["e4", "e3"]
        assert [row["event_id"] for row in page2] == ["e2", "e1"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_events_empty_when_not_started(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    assert await store.list_events() == []
