"""S2 MemoryConsolidator 真实整合单测。

骨架单测 (test_memory_consolidator_scaffolding.py) 验证 metadata=None / 未启用时
返回全零 + 后台生命周期; 本文件验证 S2 激活后 run_once 的三步真实行为
(去重/剪枝/画像归纳) + 各步异常隔离 + llm=None 跳过归纳 + protected 条目不被合并。
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from isac.core.types import LLMResponse
from isac.memory.consolidator import ConsolidationResult, MemoryConsolidator
from isac.memory.storage.metadata import MetadataStore


def _connect(store: MetadataStore) -> aiosqlite.Connection:
    """返回 aiosqlite 连接 (支持 async with 上下文管理器)。"""
    return aiosqlite.connect(store.db_path)


async def _make_store(tmp_path: str) -> MetadataStore:
    store = MetadataStore(tmp_path)
    await store.init_schema()
    return store


@pytest.fixture
async def store() -> MetadataStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    s = await _make_store(tmp.name)
    yield s
    await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


class _FakeLLM:
    """记录 chat 调用 + 按真实 LLMProvider 契约返回响应。"""

    def __init__(self, response: str = "新归纳的画像文本") -> None:
        self._response = response
        self.calls: list[dict] = []

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools, "kwargs": kwargs})
        return LLMResponse(content=self._response)


class _BoomLLM:
    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        raise RuntimeError("LLM down")


# ── 去重步骤 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_merges_similar_episodes(store: MetadataStore) -> None:
    """两条高度相似内容 (仅空白/标点差) → 较旧者被软删 (deleted=1)。"""
    old_created = int(time.time()) - 100
    new_created = int(time.time())
    await store.store_episode("a1", {"id": "ep_old", "session_id": "s1", "user_id": "u1", "content": "今天天气不错"})
    await store.store_episode("a1", {"id": "ep_new", "session_id": "s1", "user_id": "u1", "content": "今天 天气 不错"})
    # 手动设置 created_at: ep_new 较新
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET created_at = ? WHERE id = ?", (old_created, "ep_old"))
        await db.execute("UPDATE episodes SET created_at = ? WHERE id = ?", (new_created, "ep_new"))
        await db.commit()
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store, dedup_similarity=0.85,
    )
    result = await consolidator.run_once()
    assert result.merged_episodes == 1
    # ep_old (较旧) 被软删
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = ?", ("ep_old",))
        row = await cursor.fetchone()
        assert row and row[0] == 1
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = ?", ("ep_new",))
        row = await cursor.fetchone()
        assert row and row[0] == 0


@pytest.mark.asyncio
async def test_dedup_uses_memory_namespace_for_governance(store: MetadataStore) -> None:
    await store.store_episode(
        "shared-memory", {"id": "ep_old", "session_id": "s1", "user_id": "u1", "content": "相同内容"}
    )
    await store.store_episode(
        "shared-memory", {"id": "ep_new", "session_id": "s1", "user_id": "u1", "content": "相同内容"}
    )
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET created_at = 100 WHERE id = 'ep_old'")
        await db.execute("UPDATE episodes SET created_at = 200 WHERE id = 'ep_new'")
        await db.commit()

    result = await MemoryConsolidator(
        agent_id="agent-a", namespace="shared-memory", metadata=store
    ).run_once()

    assert result.merged_episodes == 1


@pytest.mark.asyncio
async def test_dedup_does_not_merge_different_private_users(store: MetadataStore) -> None:
    await store.store_episode(
        "a1", {"id": "ep_u1", "session_id": "s1", "user_id": "u1", "content": "完全相同的内容"}
    )
    await store.store_episode(
        "a1", {"id": "ep_u2", "session_id": "s2", "user_id": "u2", "content": "完全相同的内容"}
    )

    result = await MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store).run_once()

    assert result.merged_episodes == 0


@pytest.mark.asyncio
async def test_dedup_respects_protected(store: MetadataStore) -> None:
    """protected=1 的旧条目即使与新的高度相似也不会被合并 (governor 拒绝)。"""
    await store.store_episode("a1", {"id": "ep_old", "session_id": "s1", "user_id": "u1", "content": "完全相同的内容"})
    await store.store_episode("a1", {"id": "ep_new", "session_id": "s1", "user_id": "u1", "content": "完全相同的内容"})
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET protected = 1, created_at = 100 WHERE id = 'ep_old'")
        await db.execute("UPDATE episodes SET created_at = 200 WHERE id = 'ep_new'")
        await db.commit()
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store, dedup_similarity=0.85,
    )
    result = await consolidator.run_once()
    # protected 条目不被合并
    assert result.merged_episodes == 0


# ── 剪枝步骤 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prune_removes_low_importance_old_episodes(store: MetadataStore) -> None:
    """created_at 早于阈值且 importance 低于阈值 → 软删。"""
    very_old = int(time.time()) - 86400 * 60  # 60 天前
    recent = int(time.time())
    await store.store_episode("a1", {"id": "ep_old", "session_id": "s1", "user_id": "u1", "content": "陈旧低价值"})
    await store.store_episode("a1", {"id": "ep_new", "session_id": "s1", "user_id": "u1", "content": "近期内容"})
    async with _connect(store) as db:
        await db.execute(
            "UPDATE episodes SET created_at = ?, importance = 0.1 WHERE id = 'ep_old'", (very_old,)
        )
        await db.execute(
            "UPDATE episodes SET created_at = ?, importance = 0.8 WHERE id = 'ep_new'", (recent,)
        )
        await db.commit()
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store,
        prune_after_days=30, prune_importance_below=0.2,
    )
    result = await consolidator.run_once()
    assert result.pruned_episodes == 1
    async with _connect(store) as db:
        cursor = await db.execute("SELECT deleted FROM episodes WHERE id = 'ep_old'")
        row = await cursor.fetchone()
        assert row and row[0] == 1


@pytest.mark.asyncio
async def test_prune_skips_high_importance(store: MetadataStore) -> None:
    """超期但 importance 足够 → 不剪枝。"""
    very_old = int(time.time()) - 86400 * 60
    await store.store_episode("a1", {"id": "ep_old", "session_id": "s1", "user_id": "u1", "content": "陈旧但重要"})
    async with _connect(store) as db:
        await db.execute(
            "UPDATE episodes SET created_at = ?, importance = 0.8 WHERE id = 'ep_old'", (very_old,)
        )
        await db.commit()
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store,
        prune_after_days=30, prune_importance_below=0.2,
    )
    result = await consolidator.run_once()
    assert result.pruned_episodes == 0


@pytest.mark.asyncio
async def test_prune_skips_protected_and_frozen(store: MetadataStore) -> None:
    """protected/frozen 条目即使超期+低价值也永不剪枝。"""
    very_old = int(time.time()) - 86400 * 60
    await store.store_episode("a1", {"id": "ep_p", "session_id": "s1", "user_id": "u1", "content": "受保护"})
    await store.store_episode("a1", {"id": "ep_f", "session_id": "s1", "user_id": "u1", "content": "已冻结"})
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET protected=1, created_at=?, importance=0.1 WHERE id='ep_p'", (very_old,))
        await db.execute("UPDATE episodes SET frozen=1, created_at=?, importance=0.1 WHERE id='ep_f'", (very_old,))
        await db.commit()
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store,
        prune_after_days=30, prune_importance_below=0.2,
    )
    result = await consolidator.run_once()
    assert result.pruned_episodes == 0


# ── 画像归纳步骤 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_summarization_writes_back(store: MetadataStore) -> None:
    """注入 fake LLM → upsert_person_profile 被调用, updated_profiles==1。"""
    await store.store_episode("a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "我喜欢打球"})
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET user_id='u1' WHERE id='ep1'")
        await db.commit()
    fake_llm = _FakeLLM(response="用户喜欢运动, 性格开朗")
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store, llm=fake_llm,
    )
    result = await consolidator.run_once()
    assert result.updated_profiles == 1
    # profile_text 已写回
    profile = await store.get_person_profile("a1", "u1")
    assert profile and profile["profile_text"] == "用户喜欢运动, 性格开朗"
    assert len(fake_llm.calls) == 1


@pytest.mark.asyncio
async def test_profile_summarization_skipped_when_llm_none(store: MetadataStore) -> None:
    """llm=None 时画像归纳步骤跳过, 不抛异常, updated_profiles==0。"""
    await store.store_episode("a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "随便聊"})
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store, llm=None,
    )
    result = await consolidator.run_once()
    assert result.updated_profiles == 0


@pytest.mark.asyncio
async def test_profile_summarization_llm_failure_isolated(store: MetadataStore) -> None:
    """LLM 调用抛异常时该 person 被跳过, 不影响其他步骤与返回结构。"""
    await store.store_episode("a1", {"id": "ep1", "session_id": "s1", "user_id": "u1", "content": "随便聊"})
    async with _connect(store) as db:
        await db.execute("UPDATE episodes SET user_id='u1' WHERE id='ep1'")
        await db.commit()
    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=store, llm=_BoomLLM(),
    )
    result = await consolidator.run_once()
    # LLM 失败被吞, 返回 ConsolidationResult (updated_profiles=0), 不抛异常
    assert isinstance(result, ConsolidationResult)
    assert result.updated_profiles == 0


# ── 步骤隔离 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_step_isolation_does_not_break_run_once(store: MetadataStore) -> None:
    """单步失败不影响其他步骤 (governor 自身已有 protected/frozen 拒绝, 这里测异常隔离)。"""

    class _BoomMetadata:
        """所有方法抛异常的 fake metadata, 验证 run_once 不冒泡。"""

        db_path = store.db_path

        async def iter_episodes_by_namespace(self, agent_id: str):  # noqa: ANN201
            raise RuntimeError("metadata down")

    consolidator = MemoryConsolidator(
        agent_id="a1", namespace="a1", metadata=_BoomMetadata(),
    )
    result = await consolidator.run_once()  # 不抛异常
    assert isinstance(result, ConsolidationResult)
    # 加载 episodes 失败 → 早返回全零
    assert (result.merged_episodes, result.pruned_episodes, result.updated_profiles) == (0, 0, 0)


# ── _build_memory_consolidator llm 注入 ─────────────────────────


def test_build_consolidator_injects_llm() -> None:
    """_build_memory_consolidator 注入 llm 后 MemoryConsolidator 持有同一实例。"""
    from isac.runtime.assembly import _build_memory_consolidator
    from isac.runtime.config import AgentConfig

    config = AgentConfig(agent_id="a1")

    class _FakePipeline:
        namespace = "a1"
        metadata = object()

    fake_llm = _FakeLLM()
    consolidator = _build_memory_consolidator(
        config,
        {"memory": {"consolidation": {"enabled": True}}},
        _FakePipeline(),
        llm=fake_llm,
    )
    assert consolidator is not None
    assert consolidator._llm is fake_llm  # noqa: SLF001
