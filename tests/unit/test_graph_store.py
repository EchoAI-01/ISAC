"""EXP-2: GraphStore SQLite 三元组表实现测试。

覆盖:
- add_edge 写入边 (subject, relation, object, weight)
- neighbors 查询节点邻居 (返回 [(object, weight)], 可选按 relation 过滤)
- 多次 add_edge 同一边覆盖 (UPSERT)
- delete_by_namespace 按 agent_id 清理
- 跨 agent_id 命名空间隔离
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.memory.storage.graph import GraphStore


@pytest.fixture
async def store(tmp_path: Path) -> GraphStore:
    s = GraphStore(str(tmp_path / "graph.db"))
    await s.init_schema()
    return s


@pytest.mark.asyncio
async def test_init_schema_creates_edges_table(tmp_path: Path) -> None:
    s = GraphStore(str(tmp_path / "g.db"))
    await s.init_schema()
    import aiosqlite

    async with aiosqlite.connect(s.db_path) as db:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='graph_edges'")
        rows = await cursor.fetchall()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_add_edge_and_neighbors(store: GraphStore) -> None:
    await store.add_edge("a1", "user:u1", "member_of", "group:g1", weight=1.0)
    await store.add_edge("a1", "user:u2", "member_of", "group:g1", weight=0.8)
    await store.add_edge("a1", "user:u1", "friend_of", "user:u2", weight=0.9)
    # 查询 group:g1 的 member_of 邻居 (反向: 谁是 group:g1 的成员)
    # GraphStore 设计: subject → object; neighbors(node) 返回 node 作为 subject 的所有 object
    neighbors = await store.neighbors("a1", "user:u1")
    assert len(neighbors) == 2  # member_of group:g1 + friend_of user:u2
    objs = [n[0] for n in neighbors]
    assert "group:g1" in objs
    assert "user:u2" in objs


@pytest.mark.asyncio
async def test_neighbors_filter_by_relation(store: GraphStore) -> None:
    await store.add_edge("a1", "user:u1", "member_of", "group:g1")
    await store.add_edge("a1", "user:u1", "friend_of", "user:u2")
    neighbors = await store.neighbors("a1", "user:u1", relation="friend_of")
    assert len(neighbors) == 1
    assert neighbors[0][0] == "user:u2"


@pytest.mark.asyncio
async def test_add_edge_overwrites_existing(store: GraphStore) -> None:
    """同 (agent_id, subject, relation, object) 多次 add_edge 应覆盖 (UPSERT weight)。"""
    await store.add_edge("a1", "u1", "friend", "u2", weight=0.5)
    await store.add_edge("a1", "u1", "friend", "u2", weight=0.9)
    neighbors = await store.neighbors("a1", "u1", relation="friend")
    assert len(neighbors) == 1
    assert neighbors[0][1] == 0.9  # weight 被覆盖


@pytest.mark.asyncio
async def test_cross_agent_namespace_isolation(store: GraphStore) -> None:
    """不同 agent_id 的边隔离 (同 subject+relation 在不同 agent 各自独立)。"""
    await store.add_edge("a1", "u1", "friend", "u2")
    await store.add_edge("a2", "u1", "friend", "u3")
    a1_neighbors = await store.neighbors("a1", "u1", relation="friend")
    a2_neighbors = await store.neighbors("a2", "u1", relation="friend")
    assert a1_neighbors == [("u2", 1.0)]
    assert a2_neighbors == [("u3", 1.0)]


@pytest.mark.asyncio
async def test_neighbors_unknown_node_returns_empty(store: GraphStore) -> None:
    await store.add_edge("a1", "u1", "friend", "u2")
    assert await store.neighbors("a1", "unknown") == []


@pytest.mark.asyncio
async def test_delete_by_namespace(store: GraphStore) -> None:
    await store.add_edge("a1", "u1", "friend", "u2")
    await store.add_edge("a2", "u1", "friend", "u3")
    await store.delete_by_namespace("a1")
    assert await store.neighbors("a1", "u1") == []
    assert await store.neighbors("a2", "u1") == [("u3", 1.0)]
