"""EXP-1: VectorStore sqlite-vec 真实实现测试。

覆盖:
- init_schema 创建 vec0 虚拟表
- upsert 写入向量
- search KNN 查询 (返回 memory_id + distance)
- delete 删除向量
- 跨 agent_id 命名空间 (查询时由调用方过滤, VectorStore 本身不隔离)
- dimension 一致性
"""

from __future__ import annotations

from pathlib import Path

import pytest

from isac.memory.storage.vector import VectorStore


@pytest.fixture
async def store(tmp_path: Path) -> VectorStore:
    s = VectorStore(str(tmp_path / "vectors.db"), dimension=4)
    await s.init_schema()
    return s


@pytest.mark.asyncio
async def test_init_schema_creates_vec0_table(tmp_path: Path) -> None:
    s = VectorStore(str(tmp_path / "v.db"), dimension=4)
    await s.init_schema()
    # 验证 vec0 虚拟表存在
    import aiosqlite

    async with aiosqlite.connect(s.db_path) as db:
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vectors'")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "vectors"


@pytest.mark.asyncio
async def test_upsert_and_search_knn(store: VectorStore) -> None:
    # 写入 3 个向量
    await store.upsert("m1", [1.0, 0.0, 0.0, 0.0])
    await store.upsert("m2", [0.0, 1.0, 0.0, 0.0])
    await store.upsert("m3", [0.9, 0.1, 0.0, 0.0])  # 接近 m1
    # 查询接近 [1,0,0,0] 的 top 2
    results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    # m1 和 m3 应排在前面 (距离最近)
    ids = [r[0] for r in results]
    assert "m1" in ids
    assert "m3" in ids
    # m1 距离应最小 (distance 越小越相似)
    assert results[0][0] == "m1"


@pytest.mark.asyncio
async def test_search_empty_store_returns_empty(store: VectorStore) -> None:
    results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_delete_removes_vector(store: VectorStore) -> None:
    await store.upsert("m1", [1.0, 0.0, 0.0, 0.0])
    await store.upsert("m2", [0.0, 1.0, 0.0, 0.0])
    await store.delete("m1")
    results = await store.search([1.0, 0.0, 0.0, 0.0], top_k=5)
    ids = [r[0] for r in results]
    assert "m1" not in ids
    assert "m2" in ids


@pytest.mark.asyncio
async def test_upsert_overwrites_existing(store: VectorStore) -> None:
    """同 memory_id 多次 upsert 应覆盖 (不是追加)。"""
    await store.upsert("m1", [1.0, 0.0, 0.0, 0.0])
    await store.upsert("m1", [0.0, 0.0, 0.0, 1.0])  # 覆盖
    results = await store.search([0.0, 0.0, 0.0, 1.0], top_k=1)
    assert len(results) == 1
    assert results[0][0] == "m1"


@pytest.mark.asyncio
async def test_dimension_mismatch_raises(tmp_path: Path) -> None:
    """upsert 向量维度与 store.dimension 不匹配应报错 (sqlite-vec 限制)。"""
    s = VectorStore(str(tmp_path / "v.db"), dimension=4)
    await s.init_schema()
    # 写入 3 维向量到 4 维 store, sqlite-vec 会报错
    with pytest.raises(Exception):  # noqa: PT011
        await s.upsert("m1", [1.0, 0.0, 0.0])


@pytest.mark.asyncio
async def test_search_top_k_limit(store: VectorStore) -> None:
    for i in range(5):
        await store.upsert(f"m{i}", [float(i), 0.0, 0.0, 0.0])
    results = await store.search([2.0, 0.0, 0.0, 0.0], top_k=3)
    assert len(results) == 3
    # m2 (距离 0) 应排第一
    assert results[0][0] == "m2"
