"""MemoryRetrievalPipeline 单元测试。"""

from __future__ import annotations

import pytest

from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline
from isac.memory.reranker import Reranker
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore


async def make_pipeline(tmp_path, namespace: str = "agent_a", metrics=None) -> MemoryRetrievalPipeline:
    metadata = MetadataStore(str(tmp_path / "memory.db"))
    await metadata.init_schema()
    return MemoryRetrievalPipeline(
        namespace=namespace,
        metadata=metadata,
        vector=VectorStore(str(tmp_path / "vectors.db"), dimension=3),
        sparse=SparseBM25Index(),
        graph=GraphStore(str(tmp_path / "graph.db")),
        embedder=EmbeddingManager({}),
        reranker=Reranker({}),
        metrics=metrics,
    )


@pytest.mark.asyncio
async def test_store_episode_then_search_without_embedding(tmp_path) -> None:
    pipeline = await make_pipeline(tmp_path)

    memory_id = await pipeline.store_episode(
        "ISAC 正在实现 keyword 记忆检索",
        session_id="sess_1",
        user_id="user_1",
        metadata={"summary": "keyword 记忆检索", "importance": 0.9},
    )
    hits = await pipeline.search("ISAC keyword 记忆", top_k=3)

    assert memory_id
    assert len(hits) == 1
    assert hits[0].id == memory_id
    assert hits[0].content == "ISAC 正在实现 keyword 记忆检索"


@pytest.mark.asyncio
async def test_search_is_namespace_isolated(tmp_path) -> None:
    pipeline_a = await make_pipeline(tmp_path, namespace="agent_a")
    pipeline_b = await make_pipeline(tmp_path, namespace="agent_b")
    await pipeline_a.store_episode("agent_a 的私有记忆", session_id="sess_a", user_id="user_a")
    await pipeline_b.store_episode("agent_b 的私有记忆", session_id="sess_b", user_id="user_b")

    hits = await pipeline_a.search("私有记忆", top_k=10)

    assert [hit.source for hit in hits] == ["sess_a"]


@pytest.mark.asyncio
async def test_search_private_chat_excludes_other_users_memory(tmp_path) -> None:
    """pipeline.search() 传入 user_id 时, 私聊记忆应仅对发言者本人可见 (CODE_REVIEW_REPORT.md #9)。"""
    pipeline = await make_pipeline(tmp_path)
    await pipeline.store_episode("ISAC 私聊记忆 来自 user_a", session_id="sess_a", user_id="user_a")
    await pipeline.store_episode("ISAC 私聊记忆 来自 user_b", session_id="sess_b", user_id="user_b")

    hits_a = await pipeline.search("ISAC 私聊记忆", top_k=10, user_id="user_a")

    assert [hit.source for hit in hits_a] == ["sess_a"]


@pytest.mark.asyncio
async def test_search_group_chat_is_visible_to_all_members(tmp_path) -> None:
    """pipeline.search() 传入 group_id 时, 群聊记忆应对该群全部成员可见, 不按发言人收窄。"""
    pipeline = await make_pipeline(tmp_path)
    await pipeline.store_episode(
        "群聊共享记忆 来自 user_a", session_id="sess_g1", user_id="user_a", group_id="group_1"
    )
    await pipeline.store_episode(
        "群聊共享记忆 来自 user_b", session_id="sess_g1", user_id="user_b", group_id="group_1"
    )

    # user_c 身处 group_1, 即使不是发言人本人也应看到群内全部成员的共享记忆。
    hits = await pipeline.search("群聊共享记忆", top_k=10, user_id="user_c", group_id="group_1")

    assert {hit.content for hit in hits} == {"群聊共享记忆 来自 user_a", "群聊共享记忆 来自 user_b"}


@pytest.mark.asyncio
async def test_search_top_k_and_empty_query(tmp_path) -> None:
    pipeline = await make_pipeline(tmp_path)
    await pipeline.store_episode("记忆 检索 一", session_id="sess_1", user_id="user_1")
    await pipeline.store_episode("记忆 检索 二", session_id="sess_2", user_id="user_1")

    assert await pipeline.search("", top_k=5) == []
    assert len(await pipeline.search("记忆", top_k=1)) == 1


@pytest.mark.asyncio
async def test_search_and_store_episode_record_metrics(tmp_path) -> None:
    """search()/store_episode() 应记录检索/写入次数与检索延迟 (CODE_REVIEW_REPORT.md #5)。"""
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    pipeline = await make_pipeline(tmp_path, metrics=metrics)

    await pipeline.store_episode("ISAC 记忆", session_id="sess_1", user_id="user_1")
    assert metrics.counter("isac_memory_stores_total").value() == 1

    await pipeline.search("ISAC", top_k=3)
    assert metrics.counter("isac_memory_searches_total").value() == 1
    assert metrics.histogram("isac_memory_search_latency_seconds")._count == 1

    # 空 query 直接短路返回, 不算一次真正的检索尝试。
    await pipeline.search("", top_k=3)
    assert metrics.counter("isac_memory_searches_total").value() == 1


@pytest.mark.asyncio
async def test_embedding_and_reranker_default_to_safe_degraded_mode() -> None:
    embedder = EmbeddingManager({})
    reranker = Reranker({})
    vector = VectorStore(":memory:", dimension=3)

    assert embedder.is_degraded() is True
    assert embedder.get_fingerprint()["degraded"] is True
    assert await embedder.embed_query("hello") == []
    assert reranker.is_available() is False
    assert await vector.search([1.0, 0.0, 0.0]) == []
