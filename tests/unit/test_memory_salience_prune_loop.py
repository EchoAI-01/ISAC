"""阶段2-4 (P1-3) 剪枝闭环联动: 评分器 → episode.importance → consolidator 剪枝。

现有 S2 测试用 SQL 直接塞 importance 验证剪枝机制本身; 本文件证明**完整回路**:
显著度评分器产出的 importance 真正落进 episode, 并驱动 consolidator 把琐碎的旧记忆
剪掉、把值得记的旧记忆保留 —— 修复前 importance 恒 0.5, 该回路恒空转。
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import aiosqlite
import pytest

from isac.memory.consolidator import MemoryConsolidator
from isac.memory.salience import score_importance
from isac.memory.storage.metadata import MetadataStore


def _connect(store: MetadataStore) -> aiosqlite.Connection:
    return aiosqlite.connect(store.db_path)


async def _make_store(db_path: str) -> MetadataStore:
    store = MetadataStore(db_path)
    await store.init_schema()
    return store


@pytest.fixture
async def store() -> MetadataStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    s = await _make_store(tmp.name)
    yield s
    await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


async def _backdate(store: MetadataStore, episode_id: str, days_ago: int) -> None:
    """把 created_at 回拨到剪枝窗口之外 (仅改时间, importance 保持评分器写入值)。"""
    old = int(time.time()) - 86400 * days_ago
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET created_at = ? WHERE id = ?", (old, episode_id))
        await db.commit()


async def _is_deleted(store: MetadataStore, episode_id: str) -> bool:
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = ?", (episode_id,))
        row = await cursor.fetchone()
    return bool(row and row[0] == 1)


@pytest.mark.asyncio
async def test_scorer_drives_prune_end_to_end(store: MetadataStore) -> None:
    """琐碎回合 (评分器落 <0.2) 被剪; 值得记的回合 (评分器落 >0.5) 保留。"""
    # 用评分器产出 importance, 走与生产一致的 store_episode 写入路径。
    trivial_imp = score_importance("嗯", "好的呢")
    important_imp = score_importance("记住我的生日是3月5日", "已为你记录")
    # 前置断言: 分布确实跨阈值 (否则本测试无意义)。
    assert trivial_imp < 0.2 < important_imp

    await store.store_episode("a1", {
        "id": "ep_trivial", "session_id": "s1", "user_id": "u1",
        "content": "用户: 嗯\nBot: 好的呢", "importance": trivial_imp,
    })
    await store.store_episode("a1", {
        "id": "ep_important", "session_id": "s1", "user_id": "u1",
        "content": "用户: 记住我的生日是3月5日\nBot: 已为你记录", "importance": important_imp,
    })
    # 两条都回拨到 60 天前 (超出 30 天剪枝窗口) —— 区别只在 importance。
    await _backdate(store, "ep_trivial", 60)
    await _backdate(store, "ep_important", 60)

    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store,
        prune_after_days=30, prune_importance_below=0.2,
    )
    result = await consolidator.run_once()

    assert result.pruned_episodes == 1, "评分器分布应恰好剪掉 1 条琐碎记忆"
    assert await _is_deleted(store, "ep_trivial") is True
    assert await _is_deleted(store, "ep_important") is False


@pytest.mark.asyncio
async def test_recent_trivial_not_pruned_despite_low_score(store: MetadataStore) -> None:
    """时间衰减门槛仍在: 近期琐碎记忆 (未超期) 不被剪, 即使 importance 低。"""
    trivial_imp = score_importance("哈哈", "嘿嘿")
    assert trivial_imp < 0.2
    await store.store_episode("a1", {
        "id": "ep_recent_trivial", "session_id": "s1", "user_id": "u1",
        "content": "用户: 哈哈\nBot: 嘿嘿", "importance": trivial_imp,
    })
    # 不回拨 created_at (保持 now) —— 未超期。
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store,
        prune_after_days=30, prune_importance_below=0.2,
    )
    result = await consolidator.run_once()
    assert result.pruned_episodes == 0
    assert await _is_deleted(store, "ep_recent_trivial") is False
