"""N2 记忆治理业务测试。

覆盖:
- MemoryGovernor.freeze/protect/correct/delete/restore 真实 SQL 行为 + 审计日志
- protected 条目 delete 被拒绝
- correct 保留旧版本 (memory_revisions 表)
- restore 反向操作
- export 返回 list[MemoryItem]
- 不动既有 episodes 三表 schema (仅加列 + 新表)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from isac.memory.model import MemoryGovernor
from isac.memory.model.memory_item import MemoryType
from isac.memory.storage.metadata import MetadataStore


@pytest.fixture
async def store_and_governor() -> tuple[MetadataStore, MemoryGovernor]:
    """构造一个内存级 MetadataStore + MemoryGovernor fixture."""
    import asyncio

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name
    store = MetadataStore(tmp_path)
    await store.init_schema()
    governor = MemoryGovernor(store)
    # 预置一条 episode 供治理操作
    await store.store_episode("a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "原始内容"})
    yield store, governor
    # 清理临时 db 文件 (fixture 装饰器是 async, 用 to_thread 包装 blocking unlink)
    await asyncio.to_thread(lambda: Path(tmp_path).unlink(missing_ok=True))


@pytest.mark.asyncio
async def test_freeze_sets_frozen_flag_and_writes_audit(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    assert await gov.freeze("ep1", "a1") is True
    # 二次 freeze 应幂等 (仍 True)
    assert await gov.freeze("ep1", "a1") is True
    # 数据库行 frozen=1
    async with _connect(store) as db:
        cursor = await db.execute("SELECT frozen FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1
    # 审计日志有 freeze 记录
    audit = await gov.list_audit("ep1")
    assert any(a["action"] == "freeze" for a in audit)


@pytest.mark.asyncio
async def test_protect_sets_protected_flag_and_writes_audit(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    assert await gov.protect("ep1", "a1") is True
    async with _connect(store) as db:
        cursor = await db.execute("SELECT protected FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    audit = await gov.list_audit("ep1")
    assert any(a["action"] == "protect" for a in audit)


@pytest.mark.asyncio
async def test_correct_writes_new_version_and_keeps_history(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    assert await gov.correct("ep1", "纠正后内容", "a1") is True
    # episodes.content 已更新为新内容
    async with _connect(store) as db:
        cursor = await db.execute("SELECT content, corrected_by FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "纠正后内容"
        assert row[1] is not None  # corrected_by 指向 revision_id
    # memory_revisions 表保留旧版本
    async with _connect(store) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM memory_revisions WHERE item_id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] >= 1


@pytest.mark.asyncio
async def test_correct_rejects_when_item_is_frozen(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    """CR2-Fix-13: frozen (不再自动更新) 的条目此前仍能被 correct 改写内容。"""
    store, gov = store_and_governor
    await gov.freeze("ep1", "a1")
    assert await gov.correct("ep1", "试图篡改", "a1") is False
    async with _connect(store) as db:
        cursor = await db.execute("SELECT content FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == "原始内容"  # 内容未被改写


@pytest.mark.asyncio
async def test_correct_truncates_overlong_content(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    """CR2-Fix-13: new_content 此前无长度限制, 可被当作任意大小文本载体。"""
    store, gov = store_and_governor
    overlong = "字" * 50_000  # 每个中文字符 3 字节 UTF-8, 远超 20_000 字节上限
    assert await gov.correct("ep1", overlong, "a1") is True
    async with _connect(store) as db:
        cursor = await db.execute("SELECT content FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None
        stored = row[0]
        assert len(stored.encode("utf-8")) <= 20_000
        assert stored.endswith("已截断)")


@pytest.mark.asyncio
async def test_delete_soft_deletes_and_writes_audit(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    assert await gov.delete("ep1", "a1") is True
    # 软删除: deleted=1, 行仍在
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1
    audit = await gov.list_audit("ep1")
    assert any(a["action"] == "delete" for a in audit)


@pytest.mark.asyncio
async def test_delete_protected_item_is_rejected(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    await gov.protect("ep1", "a1")
    assert await gov.delete("ep1", "a1") is False  # protected 拒绝
    # 行未被删除
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == 0


@pytest.mark.asyncio
async def test_restore_resets_deleted_and_frozen(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    await gov.freeze("ep1", "a1")
    await gov.delete("ep1", "a1")
    assert await gov.restore("ep1", "a1") is True
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted, frozen FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 0  # deleted 复位
        assert row[1] == 0  # frozen 复位


@pytest.mark.asyncio
async def test_export_returns_list_of_memoryitem(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    # 预置第二条 episode
    await store.store_episode("a1", {"id": "ep2", "session_id": "s1", "user_id": "u1", "content": "第二条"})
    items = await gov.export("a1")
    assert len(items) == 2
    assert all(item.agent_id == "a1" for item in items)
    assert all(item.memory_type is MemoryType.EPISODE for item in items)
    contents = {item.content for item in items}
    assert "原始内容" in contents
    assert "第二条" in contents


@pytest.mark.asyncio
async def test_export_paginates_with_limit_and_offset(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    """CR2-Fix-15: export() 此前一次性吐出全部记忆, 无分页; 加 limit/offset 后
    单次调用只返回 limit 条, 配合 offset 能翻页取完。"""
    store, gov = store_and_governor
    # fixture 已预置 ep1; 再补 2 条, 凑够 3 条 (ep1/ep2/ep3)
    await store.store_episode("a1", {"id": "ep2", "session_id": "s1", "user_id": "u1", "content": "第二条"})
    await store.store_episode("a1", {"id": "ep3", "session_id": "s1", "user_id": "u1", "content": "第三条"})

    page1 = await gov.export("a1", limit=2, offset=0)
    assert len(page1) == 2
    page2 = await gov.export("a1", limit=2, offset=2)
    assert len(page2) == 1

    all_ids = {item.id for item in page1} | {item.id for item in page2}
    assert all_ids == {"ep1", "ep2", "ep3"}  # 两页拼起来正好翻完


@pytest.mark.asyncio
async def test_freeze_nonexistent_returns_false(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    _store, gov = store_and_governor
    assert await gov.freeze("nonexistent_id", "a1") is False


# ── CR2-Fix-11: 治理操作按 agent_id 校验, 拒绝跨 Agent 操作 ──────────


@pytest.mark.asyncio
async def test_freeze_rejects_item_belonging_to_different_agent(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    """ep1 属于 a1; 用 a2 的 agent_id 调用 freeze 应被拒绝, 而非误判为"存在"。"""
    store, gov = store_and_governor
    assert await gov.freeze("ep1", "a2") is False
    async with _connect(store) as db:
        cursor = await db.execute("SELECT frozen FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == 0  # 未被冻结


@pytest.mark.asyncio
async def test_protect_rejects_item_belonging_to_different_agent(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    _store, gov = store_and_governor
    assert await gov.protect("ep1", "a2") is False


@pytest.mark.asyncio
async def test_correct_rejects_item_belonging_to_different_agent(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    assert await gov.correct("ep1", "被篡改的内容", "a2") is False
    async with _connect(store) as db:
        cursor = await db.execute("SELECT content FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == "原始内容"  # 内容未被跨 Agent 篡改


@pytest.mark.asyncio
async def test_delete_rejects_item_belonging_to_different_agent(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    store, gov = store_and_governor
    assert await gov.delete("ep1", "a2") is False
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == 0  # 未被删除


@pytest.mark.asyncio
async def test_restore_rejects_item_belonging_to_different_agent(
    store_and_governor: tuple[MetadataStore, MemoryGovernor],
) -> None:
    """先用 a1 冻结 (合法), 再用 a2 尝试 restore, 应被拒绝且冻结状态不变。"""
    store, gov = store_and_governor
    await gov.freeze("ep1", "a1")
    assert await gov.restore("ep1", "a2") is False
    async with _connect(store) as db:
        cursor = await db.execute("SELECT frozen FROM episodes WHERE id = ?", ("ep1",))
        row = await cursor.fetchone()
        assert row is not None and row[0] == 1  # 仍处于冻结状态


# ── 辅助 ────────────────────────────────────────────────────────


class _AsyncCtx:
    """context manager 包装 aiosqlite.connect."""

    def __init__(self, store: MetadataStore) -> None:
        self._store = store

    async def __aenter__(self):
        import aiosqlite

        self._db = await aiosqlite.connect(self._store.db_path)
        return self._db

    async def __aexit__(self, *exc: object) -> None:
        await self._db.close()


def _connect(store: MetadataStore) -> _AsyncCtx:
    return _AsyncCtx(store)


# ── R8: 治理同步稠密向量 ──────────────────────────────────────────


class _FakeVectorStore:
    """最小 VectorStore 替身: 记录 delete 调用, 供断言。"""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, memory_id: str) -> None:
        self.deleted.append(memory_id)


@pytest.mark.asyncio
async def test_governor_delete_calls_vector_delete_when_resolver_injected() -> None:
    """R8: 注入 vector_resolver 后 delete 同步调 VectorStore.delete(memory_id)。"""
    import asyncio
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        store = MetadataStore(tmp.name)
        await store.init_schema()
        await store.store_episode(
            "a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "原始"}
        )
        fake_vector = _FakeVectorStore()
        # vector_resolver 返回 _FakeVectorStore 实例
        governor = MemoryGovernor(
            store, vector_resolver=lambda namespace: fake_vector,
        )
        ok = await governor.delete("ep1", "a1")
        assert ok is True
        # 应该已调用 vector.delete("ep1")
        assert fake_vector.deleted == ["ep1"]
    finally:
        await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


@pytest.mark.asyncio
async def test_governor_delete_skips_vector_when_resolver_none() -> None:
    """R8: 未注入 vector_resolver 时 delete 跳过 vector 同步 (向后兼容, 不抛)。"""
    import asyncio
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        store = MetadataStore(tmp.name)
        await store.init_schema()
        await store.store_episode(
            "a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "原始"}
        )
        governor = MemoryGovernor(store)  # 无 vector_resolver
        ok = await governor.delete("ep1", "a1")
        assert ok is True  # 不抛异常即可
    finally:
        await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


@pytest.mark.asyncio
async def test_governor_correct_calls_vector_delete_to_remove_stale_embedding() -> None:
    """R8: correct 后旧向量与新内容不匹配, 删除避免被召回。"""
    import asyncio
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        store = MetadataStore(tmp.name)
        await store.init_schema()
        await store.store_episode(
            "a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "原始"}
        )
        fake_vector = _FakeVectorStore()
        governor = MemoryGovernor(
            store, vector_resolver=lambda namespace: fake_vector,
        )
        ok = await governor.correct("ep1", "新内容", "a1")
        assert ok is True
        assert fake_vector.deleted == ["ep1"]
    finally:
        await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


@pytest.mark.asyncio
async def test_governor_restore_calls_vector_delete_to_remove_stale_embedding() -> None:
    """R8: restore 后旧向量与新内容不匹配 (中间被纠正过), 删除避免被召回。"""
    import asyncio
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        store = MetadataStore(tmp.name)
        await store.init_schema()
        await store.store_episode(
            "a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "原始"}
        )
        fake_vector = _FakeVectorStore()
        governor = MemoryGovernor(
            store, vector_resolver=lambda namespace: fake_vector,
        )
        # 先 delete 再 restore
        await governor.delete("ep1", "a1")
        fake_vector.deleted.clear()
        ok = await governor.restore("ep1", "a1")
        assert ok is True
        assert fake_vector.deleted == ["ep1"]
    finally:
        await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


@pytest.mark.asyncio
async def test_governor_vector_sync_failure_does_not_block_governance() -> None:
    """R8: vector.delete 异常不应阻塞治理操作本身 (失败只记 warning)。"""
    import asyncio
    import tempfile

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        store = MetadataStore(tmp.name)
        await store.init_schema()
        await store.store_episode(
            "a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "原始"}
        )

        class _FailingVectorStore:
            async def delete(self, memory_id: str) -> None:
                raise RuntimeError("vector db locked")

        governor = MemoryGovernor(
            store, vector_resolver=lambda namespace: _FailingVectorStore(),
        )
        ok = await governor.delete("ep1", "a1")
        # 治理本身成功 (vector 同步失败只记日志)
        assert ok is True
    finally:
        await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))
