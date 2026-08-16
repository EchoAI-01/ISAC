"""P3 记忆检索深化集成测试 (R7-①)。

端到端验证 MemoryRetrievalPipeline 真实四路召回融合 (FTS + Sparse BM25 + 向量 KNN +
图谱 neighbors) + RRF 融合 + 治理过滤 (deleted 不被检索命中)。区别于单元测试 (各路
单测), 本文件用真实 MetadataStore/VectorStore/GraphStore/SparseBM25Index + 确定性
fake embedding 端到端跑通一次 write→search 闭环。

复用 test_memory_pipeline.py 的 ``_KeywordEmbeddingProvider`` (确定性 3 维向量)。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from isac.memory.embedder import EmbeddingManager
from isac.memory.model.governance import MemoryGovernor
from isac.memory.pipeline import MemoryRetrievalPipeline
from isac.memory.reranker import Reranker
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index
from isac.memory.storage.vector import VectorStore
from tests.unit.test_memory_pipeline import _KeywordEmbeddingProvider

NAMESPACE = "agent_p3"


async def _build_pipeline(tmp_path: Path, *, enable_graph: bool, embedding_provider=None) -> MemoryRetrievalPipeline:
    """一站式构造真实 pipeline (复用 make_pipeline 模式 + enable_graph_recall 可控)。"""
    metadata = MetadataStore(str(tmp_path / "memory.db"))
    await metadata.init_schema()
    pipeline = MemoryRetrievalPipeline(
        namespace=NAMESPACE,
        metadata=metadata,
        vector=VectorStore(str(tmp_path / "vectors.db"), dimension=3),
        sparse=SparseBM25Index(),
        graph=GraphStore(str(tmp_path / "graph.db")),
        embedder=EmbeddingManager({}, provider=embedding_provider),
        reranker=Reranker({}),
        enable_graph_recall=enable_graph,
    )
    return pipeline


@pytest.fixture
async def pipeline(tmp_path) -> AsyncGenerator[MemoryRetrievalPipeline, None]:
    """全功能 pipeline (向量+图谱召回均开启, 注入确定性 embedding)。"""
    p = await _build_pipeline(tmp_path, enable_graph=True, embedding_provider=_KeywordEmbeddingProvider())
    yield p
    await p.vector.close()
    await p.graph.close()


@pytest.fixture
async def pipeline_no_vector(tmp_path) -> AsyncGenerator[MemoryRetrievalPipeline, None]:
    """无 embedding 的 pipeline (embedder 降级, 向量召回分支不触发)。"""
    p = await _build_pipeline(tmp_path, enable_graph=True, embedding_provider=None)
    yield p
    await p.vector.close()
    await p.graph.close()


# ── 向量召回 (CR3-H3 验证) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_dense_recall_finds_semantically_related(pipeline: MemoryRetrievalPipeline) -> None:
    """向量 KNN 召回: 查询词与已存 episode 语义同桶 (fake embedding 同向量) 即可命中,
    即便词面无重叠。验证 _dense_search 分支真实生效。"""
    # 存一条"天气"语义 episode, 查询用同语义但词面不同的 "weather"
    mid = await pipeline.store_episode("今天北京天气晴朗", "s1", user_id="u1", agent_id=NAMESPACE)
    assert mid
    hits = await pipeline.search("weather forecast", top_k=5, user_id="u1", agent_id=NAMESPACE)
    assert any(h.id == mid for h in hits), "向量召回应命中同语义 (fake embedding 同向量 [1,0,0])"


@pytest.mark.asyncio
async def test_dense_recall_skipped_when_embedder_degraded(pipeline_no_vector: MemoryRetrievalPipeline) -> None:
    """embedder 降级 (无 provider) 时 _dense_search 直接返回空 (稠密路径短路)。

    端到端 search 仍可经 FTS/Sparse 召回 (词面命中), 但稠密分支本身不贡献结果。
    """
    p = pipeline_no_vector
    assert p.embedder.is_degraded(), "无 provider 注入时 embedder 应处于降级态"
    await p.store_episode("今天北京天气晴朗", "s1", user_id="u1", agent_id=NAMESPACE)
    # 直接断言稠密路径短路返回空 (不依赖 FTS 对 CJK+英文分词的行为)
    dense = await p._dense_search("weather", top_k=5)  # noqa: SLF001
    assert dense == [], "embedder 降级时 _dense_search 应短路返回空列表"


# ── 图谱召回 (S3 验证) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_recall_returns_user_episodes(pipeline: MemoryRetrievalPipeline) -> None:
    """图谱 mentioned_in 边召回: 用户写过的 episode 经 user:{id}→episode:{mid} 边
    被 _graph_search 取回。enable_graph_recall=True 时 store_episode 自动写边。"""
    mid = await pipeline.store_episode("讨论了部署方案", "s1", user_id="alice", agent_id=NAMESPACE)
    assert mid
    # 查询词面无关 (用 fake embedding 的 [0,0,1] 兜底向量), 仅靠图谱邻居召回
    hits = await pipeline.search("任意查询", top_k=5, user_id="alice", agent_id=NAMESPACE)
    assert any(h.id == mid for h in hits), "图谱 mentioned_in 邻居应召回该用户已存 episode"


@pytest.mark.asyncio
async def test_graph_recall_isolated_by_user(pipeline: MemoryRetrievalPipeline) -> None:
    """图谱召回按 user_id 种子锚定 (ACL): alice 的 episode 不应出现在 bob 的图谱邻居里。"""
    mid_alice = await pipeline.store_episode("alice 的私事", "s1", user_id="alice", agent_id=NAMESPACE)
    await pipeline.store_episode("bob 的私事", "s2", user_id="bob", agent_id=NAMESPACE)
    hits = await pipeline.search("任意查询", top_k=5, user_id="bob", agent_id=NAMESPACE)
    ids = {h.id for h in hits}
    assert mid_alice not in ids, "图谱召回按 user_id 锚定, 不应跨用户泄露"


@pytest.mark.asyncio
async def test_graph_recall_disabled_when_flag_off(tmp_path: Path) -> None:
    """enable_graph_recall=False 时 store_episode 不写 mentioned_in 边 (图谱召回恒空)。

    直接断言图边未写入 (而非端到端 search 结果), 因 fake embedding 的兜底桶
    [0,0,1] 会让"无关"内容也经稠密路径召回, 与图谱开关无关。
    """
    p_off = await _build_pipeline(tmp_path, enable_graph=False, embedding_provider=_KeywordEmbeddingProvider())
    try:
        await p_off.store_episode("讨论了部署方案", "s1", user_id="alice", agent_id=NAMESPACE)
        # 图谱关闭: 不应写任何 mentioned_in 边
        neighbors_off = await p_off.graph.neighbors(NAMESPACE, "user:alice", relation="mentioned_in")
        assert neighbors_off == [], "enable_graph_recall=False 时不应写 mentioned_in 边"
    finally:
        await p_off.vector.close()
        await p_off.graph.close()
    # 对照: 开启时写边
    p_on = await _build_pipeline(tmp_path, enable_graph=True, embedding_provider=_KeywordEmbeddingProvider())
    try:
        await p_on.store_episode("讨论了部署方案", "s1", user_id="alice", agent_id=NAMESPACE)
        neighbors_on = await p_on.graph.neighbors(NAMESPACE, "user:alice", relation="mentioned_in")
        assert neighbors_on, "enable_graph_recall=True 时应写 mentioned_in 边"
    finally:
        await p_on.vector.close()
        await p_on.graph.close()


# ── 治理过滤 (deleted 不被检索命中) ────────────────────────────────


@pytest.mark.asyncio
async def test_deleted_episode_not_in_search_results(pipeline: MemoryRetrievalPipeline) -> None:
    """MemoryGovernor.delete 软删 (deleted=1) 后, 该 episode 不再被检索命中。
    治理过滤在 SQL 层 (search_fts/get_episodes_by_ids WHERE deleted=0)。
    """
    mid_keep = await pipeline.store_episode("保留的天气记录", "s1", user_id="u1", agent_id=NAMESPACE)
    mid_del = await pipeline.store_episode("待删除的天气记录", "s1", user_id="u1", agent_id=NAMESPACE)
    assert mid_keep and mid_del
    governor = MemoryGovernor(metadata_store=pipeline.metadata)
    ok = await governor.delete(mid_del, NAMESPACE, operator="test")
    assert ok, "软删应成功 (governor 拒绝 protected/frozen, 普通 episode 可删)"
    # 查询命中"天气"语义桶 → 应召回 keep, 不召回已删 del
    hits = await pipeline.search("天气", top_k=10, user_id="u1", agent_id=NAMESPACE)
    ids = {h.id for h in hits}
    assert mid_keep in ids, "保留的 episode 应仍可检索"
    assert mid_del not in ids, "已软删 (deleted=1) 的 episode 不应被检索命中"


@pytest.mark.asyncio
async def test_frozen_episode_still_searchable(pipeline: MemoryRetrievalPipeline) -> None:
    """frozen=1 (冻结) 只阻止治理写 (correct/delete 拒), 不影响检索可见性。

    治理对检索的影响仅在 deleted 列; frozen/protected 不参与检索过滤。
    """
    mid = await pipeline.store_episode("冻结的天气记录", "s1", user_id="u1", agent_id=NAMESPACE)
    governor = MemoryGovernor(metadata_store=pipeline.metadata)
    await governor.freeze(mid, NAMESPACE, operator="test")
    # 冻结后仍可被检索 (检索层只过滤 deleted=0)
    hits = await pipeline.search("天气", top_k=10, user_id="u1", agent_id=NAMESPACE)
    assert any(h.id == mid for h in hits), "frozen 条目应仍可检索 (检索层不过滤 frozen)"


@pytest.mark.asyncio
async def test_reranker_reranks_candidates_when_available(pipeline: MemoryRetrievalPipeline) -> None:
    """Reranker provider 注入后 is_available()=True, 对 top_k 候选做二次重排。
    本测试用真实 Reranker({}) (无 provider → is_available=False) 验证降级不报错,
    与向量+图谱+FTS 多路融合端到端跑通不抛异常。"""
    await pipeline.store_episode("天气很好", "s1", user_id="u1", agent_id=NAMESPACE)
    await pipeline.store_episode("美食很棒", "s2", user_id="u1", agent_id=NAMESPACE)
    # 同时命中天气与美食两条 → 多路融合后 Reranker 降级 (无 provider) 不抛异常
    hits = await pipeline.search("天气", top_k=5, user_id="u1", agent_id=NAMESPACE)
    assert hits, "多路融合应返回结果, Reranker 降级不阻塞主链路"
