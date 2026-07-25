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


@pytest.mark.asyncio
async def test_aggregate_empty_store_returns_empty_list(tmp_path) -> None:
    """空库且不分组时应返回 [], 而不是一行全 None/0 的幻影汇总。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        assert await store.aggregate() == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_without_group_by_returns_single_global_summary(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="a", usage=TokenUsage(prompt_tokens=10, completion_tokens=5)),
                _event(event_id="b", usage=TokenUsage(prompt_tokens=20, completion_tokens=15)),
            ]
        )
        summary = await store.aggregate()
        assert len(summary) == 1
        assert summary[0]["request_count"] == 2
        assert summary[0]["prompt_tokens"] == 30
        assert summary[0]["completion_tokens"] == 20
        assert summary[0]["total_tokens"] == 50
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_groups_by_agent_id(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="a1", agent_id="agent-a", usage=TokenUsage(total_tokens=10)),
                _event(event_id="a2", agent_id="agent-a", usage=TokenUsage(total_tokens=5)),
                _event(event_id="b1", agent_id="agent-b", usage=TokenUsage(total_tokens=7)),
            ]
        )
        rows = await store.aggregate({"group_by": ["agent_id"]})
        by_agent = {row["agent_id"]: row for row in rows}
        assert by_agent["agent-a"]["request_count"] == 2
        assert by_agent["agent-a"]["total_tokens"] == 15
        assert by_agent["agent-b"]["request_count"] == 1
        assert by_agent["agent-b"]["total_tokens"] == 7
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_groups_by_multiple_dimensions(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="1", provider="P1", model="m1"),
                _event(event_id="2", provider="P1", model="m2"),
                _event(event_id="3", provider="P2", model="m1"),
            ]
        )
        rows = await store.aggregate({"group_by": ["provider", "model"]})
        keys = {(row["provider"], row["model"]) for row in rows}
        assert keys == {("P1", "m1"), ("P1", "m2"), ("P2", "m1")}
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_groups_by_fallback(tmp_path) -> None:
    """Fix-18: group_by=["fallback"] 之前无测试覆盖 (_GROUP_BY_EXPRESSIONS 里
    "fallback" 映射到 SQL 表达式 "(fallback_from IS NOT NULL)", 属于唯一一个
    不是"列名原样输出"的分组维度, 结果行还要经过 bool() 转换, 值得单独锁定)。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="1", fallback_from=None),
                _event(event_id="2", fallback_from=None),
                _event(event_id="3", fallback_from="provider-a/model-x"),
            ]
        )
        rows = await store.aggregate({"group_by": ["fallback"]})
        by_fallback = {row["fallback"]: row for row in rows}
        assert by_fallback[False]["request_count"] == 2
        assert by_fallback[True]["request_count"] == 1
        assert isinstance(next(iter(by_fallback)), bool)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_ignores_non_whitelisted_group_by_keys(tmp_path) -> None:
    """group_by 里的非白名单条目 (可能是恶意输入) 被忽略, 不拼进 SQL、不报错。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many([_event(event_id="a", agent_id="agent-a")])
        rows = await store.aggregate({"group_by": ["agent_id", "id; DROP TABLE model_usage_events; --"]})
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "agent-a"
        assert "id; DROP TABLE model_usage_events; --" not in rows[0]
        # 确认表真的没被删
        assert await store.list_events(limit=10) != []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_time_bucket_groups_by_hour(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        hour1 = 1_700_000_000  # 任意基准时间戳, 整点
        hour1_plus_100s = hour1 + 100
        hour2 = hour1 + 3600
        await store.insert_many(
            [
                _event(event_id="a", created_at=hour1),
                _event(event_id="b", created_at=hour1_plus_100s),
                _event(event_id="c", created_at=hour2),
            ]
        )
        rows = await store.aggregate({"group_by": ["time_bucket"], "bucket": "hour"})
        assert len(rows) == 2
        counts = sorted(row["request_count"] for row in rows)
        assert counts == [1, 2]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_combines_where_filters_with_group_by(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="a", agent_id="agent-a", created_at=100),
                _event(event_id="b", agent_id="agent-a", created_at=999_999),
                _event(event_id="c", agent_id="agent-b", created_at=999_999),
            ]
        )
        rows = await store.aggregate({"group_by": ["agent_id"], "from_ts": 0, "to_ts": 200})
        assert len(rows) == 1
        assert rows[0]["agent_id"] == "agent-a"
        assert rows[0]["request_count"] == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_sums_estimated_cost_across_group(tmp_path) -> None:
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many(
            [
                _event(event_id="a", estimated_cost="0.10"),
                _event(event_id="b", estimated_cost="0.25"),
            ]
        )
        summary = await store.aggregate()
        assert float(summary[0]["estimated_cost_sum"]) == pytest.approx(0.35)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_aggregate_estimated_cost_sum_none_when_all_unknown(tmp_path) -> None:
    """未知价格不伪造成本: 组内全部 estimated_cost=None 时汇总也应是 None, 不是 0。"""
    store = UsageStore(str(tmp_path / "usage.db"))
    await store.start()
    try:
        await store.insert_many([_event(event_id="a", estimated_cost=None)])
        summary = await store.aggregate()
        assert summary[0]["estimated_cost_sum"] is None
    finally:
        await store.stop()
