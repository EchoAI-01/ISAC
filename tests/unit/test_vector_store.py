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


@pytest.mark.asyncio
async def test_close_shares_lock_with_upsert_cannot_interrupt_transaction(store: VectorStore) -> None:
    """Fix-26 回归: close() 之前不持锁, 可能在 upsert 的 DELETE→INSERT→commit
    事务执行中途把连接关掉 (触发 "Cannot operate on a closed database", 被
    调用方 broad except 吞掉表现为一条记忆写入静默丢失)。现在 close() 必须
    等同一把 _init_lock 释放才能真正执行——用"锁被占用期间 close() 不能真的
    把 _db 置空"直接验证互斥性, 而不是依赖不确定的调度时序去偶然触发旧 bug。"""
    import asyncio

    async with store._init_lock:
        close_task = asyncio.create_task(store.close())
        await asyncio.sleep(0.01)  # 给 close_task 机会尝试获取锁 (应被阻塞住)
        assert not close_task.done()
        assert store._db is not None  # 锁被占用期间, close() 不能真的执行
    await close_task
    assert store._db is None


@pytest.mark.asyncio
async def test_search_shares_lock_cannot_run_while_lock_held_elsewhere(store: VectorStore) -> None:
    """Fix-26: search() (读路径) 之前完全不接入锁, close() 可以在查询执行中途
    把连接关掉。现在 search() 必须等锁释放才能真正执行查询——用"锁被占用期间
    search() 还在等待"直接验证互斥性。"""
    import asyncio

    await store.upsert("m1", [1.0, 0.0, 0.0, 0.0])
    async with store._init_lock:
        search_task = asyncio.create_task(store.search([1.0, 0.0, 0.0, 0.0], top_k=5))
        await asyncio.sleep(0.01)
        assert not search_task.done()  # 锁被占用期间, search() 必须还在等锁
    results = await search_task
    assert results and results[0][0] == "m1"


@pytest.mark.asyncio
async def test_close_is_idempotent(store: VectorStore) -> None:
    """close() 可重复调用, 第二次是安全的 no-op。"""
    await store.close()
    assert store._db is None
    await store.close()  # 不应抛异常
    assert store._db is None


@pytest.mark.asyncio
async def test_purge_closes_connection_and_removes_db_file(tmp_path: Path) -> None:
    """Fix-26: purge() 下沉了原来在 runtime/manager.py 手工做的"关闭连接+删
    文件"逻辑 (R7), 供 namespace 级清理直接复用, 调用方不需要再用 getattr
    猜测 close()/db_path 是否存在。"""
    db_path = tmp_path / "vectors.db"
    s = VectorStore(str(db_path), dimension=4)
    await s.init_schema()
    await s.upsert("m1", [1.0, 0.0, 0.0, 0.0])
    assert db_path.exists()

    await s.purge()
    assert s._db is None
    assert not db_path.exists()


@pytest.mark.asyncio
async def test_purge_on_memory_db_skips_file_removal() -> None:
    """:memory: 数据库没有真实文件, purge() 不应尝试删除任何路径而报错。"""
    s = VectorStore(":memory:", dimension=4)
    await s.init_schema()
    await s.purge()  # 不应抛异常
    assert s._db is None


@pytest.mark.asyncio
async def test_purge_before_init_schema_is_safe(tmp_path: Path) -> None:
    """从未 init_schema 就 purge() (namespace 存在但从未真正写入过) 应安全跳过。"""
    s = VectorStore(str(tmp_path / "never-initialized.db"), dimension=4)
    await s.purge()  # 不应抛异常 (没有连接可关, 没有文件可删)
    assert s._db is None


@pytest.mark.asyncio
async def test_init_schema_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    """R6: init_schema 后连接应启用 WAL 模式 + busy_timeout, 防止并发写 SQLITE_BUSY。"""
    s = VectorStore(str(tmp_path / "v.db"), dimension=4)
    await s.init_schema()
    assert s._db is not None
    # journal_mode 是数据库级别持久化属性
    cursor = await s._db.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    assert row is not None and row[0].lower() == "wal"
    # busy_timeout 是 connection 级别, 当前连接应已设为 5000
    cursor = await s._db.execute("PRAGMA busy_timeout")
    row = await cursor.fetchone()
    assert row is not None and int(row[0]) == 5000
    await s.close()
