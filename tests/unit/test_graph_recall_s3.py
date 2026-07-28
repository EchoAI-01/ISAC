"""S3 图谱召回 + Reranker 注入真实行为单测。

骨架单测 (test_graph_recall_scaffolding.py) 验证 enable_graph_recall=False
+ 无 user_id/group_id 时恒空 (零行为变化基线); 本文件验证 S3 激活后真实
行为: store_episode 写 mentioned_in 边; _graph_search 种子→邻居→memory_id;
enable_graph_recall=False 时不写边; Reranker provider 注入后 is_available=True。
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from isac.memory.embedder import EmbeddingManager
from isac.memory.pipeline import MemoryRetrievalPipeline
from isac.memory.storage.graph import GraphStore
from isac.memory.storage.metadata import MetadataStore
from isac.memory.storage.sparse import SparseBM25Index


@pytest.fixture
async def graph_store() -> GraphStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = GraphStore(tmp.name)
    await store.init_schema()
    yield store
    await store.close()
    await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


@pytest.fixture
async def metadata_store() -> MetadataStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = MetadataStore(tmp.name)
    await store.init_schema()
    yield store
    await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


def _pipeline(
    metadata: MetadataStore | None = None,
    graph: GraphStore | None = None,
    *,
    enable_graph_recall: bool,
) -> MemoryRetrievalPipeline:
    """构造一个可调测的 pipeline (metadata/graph 真实文件; vector/sparse/embedder stub)。"""
    return MemoryRetrievalPipeline(
        namespace="a1",
        metadata=metadata or object(),  # type: ignore[arg-type]
        vector=object(),  # type: ignore[arg-type]
        sparse=SparseBM25Index() if metadata is not None else object(),  # type: ignore[arg-type]
        graph=graph or object(),  # type: ignore[arg-type]
        embedder=EmbeddingManager({}),  # 默认降级 (is_degraded=True), 不调 vector
        enable_graph_recall=enable_graph_recall,
    )


# ── _graph_search 真实召回 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_search_disabled_returns_empty(graph_store: GraphStore) -> None:
    """enable_graph_recall=False 时恒空, 即使有种子也不查 graph。"""
    await graph_store.add_edge("a1", "user:u1", "mentioned_in", "episode:m1")
    pipeline = _pipeline(graph=graph_store, enable_graph_recall=False)
    assert await pipeline._graph_search("q", top_k=10, user_id="u1") == []


@pytest.mark.asyncio
async def test_graph_search_no_seed_returns_empty(graph_store: GraphStore) -> None:
    """enable=True 但无 user_id/group_id (无 ACL 锚点) → 不查 graph, 返回空。"""
    await graph_store.add_edge("a1", "user:u1", "mentioned_in", "episode:m1")
    pipeline = _pipeline(graph=graph_store, enable_graph_recall=True)
    assert await pipeline._graph_search("q", top_k=10) == []


@pytest.mark.asyncio
async def test_graph_search_returns_memory_ids_by_weight(graph_store: GraphStore) -> None:
    """enable=True + 种子 user_id → 邻居 episode:m1/m2/m3 按 weight 降序去重。"""
    await graph_store.add_edge("a1", "user:u1", "mentioned_in", "episode:m1", weight=0.3)
    await graph_store.add_edge("a1", "user:u1", "mentioned_in", "episode:m2", weight=0.9)
    await graph_store.add_edge("a1", "user:u1", "mentioned_in", "episode:m3", weight=0.5)
    pipeline = _pipeline(graph=graph_store, enable_graph_recall=True)
    result = await pipeline._graph_search("q", top_k=10, user_id="u1")
    # 按 weight 降序
    assert [mid for mid, _ in result] == ["m2", "m3", "m1"]


@pytest.mark.asyncio
async def test_graph_search_group_seed_also_resolved(graph_store: GraphStore) -> None:
    """group_id 种子的邻居也取回。"""
    await graph_store.add_edge("a1", "group:g1", "mentioned_in", "episode:gm1", weight=1.0)
    pipeline = _pipeline(graph=graph_store, enable_graph_recall=True)
    result = await pipeline._graph_search("q", top_k=10, group_id="g1")
    assert result == [("gm1", 1.0)]


@pytest.mark.asyncio
async def test_graph_search_dedupes_same_episode(graph_store: GraphStore) -> None:
    """同一 episode 在 user + group 两条边出现, 去重保留较大 weight。"""
    await graph_store.add_edge("a1", "user:u1", "mentioned_in", "episode:dup", weight=0.3)
    await graph_store.add_edge("a1", "group:g1", "mentioned_in", "episode:dup", weight=0.7)
    pipeline = _pipeline(graph=graph_store, enable_graph_recall=True)
    result = await pipeline._graph_search("q", top_k=10, user_id="u1", group_id="g1")
    assert result == [("dup", 0.7)]


@pytest.mark.asyncio
async def test_graph_search_failure_degrades_to_empty() -> None:
    """graph.neighbors 抛异常时 _graph_search 降级返回 []。"""

    class _BoomGraph:
        async def neighbors(self, *args, **kwargs):  # noqa: ANN201
            raise RuntimeError("graph down")

    pipeline = _pipeline(graph=_BoomGraph(), enable_graph_recall=True)  # type: ignore[arg-type]
    assert await pipeline._graph_search("q", top_k=10, user_id="u1") == []


# ── store_episode 写边 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_episode_writes_mentioned_in_edges(
    metadata_store: MetadataStore, graph_store: GraphStore
) -> None:
    """enable_graph_recall=True 时 store_episode 成功后写 user/group → episode 边。"""
    pipeline = _pipeline(metadata=metadata_store, graph=graph_store, enable_graph_recall=True)
    memory_id = await pipeline.store_episode(
        "聊天气", session_id="s1", user_id="u1", agent_id="a1", group_id="g1",
    )
    assert memory_id
    neighbors = await graph_store.neighbors("a1", "user:u1", "mentioned_in")
    assert (f"episode:{memory_id}", 1.0) in neighbors
    neighbors_g = await graph_store.neighbors("a1", "group:g1", "mentioned_in")
    assert (f"episode:{memory_id}", 1.0) in neighbors_g


@pytest.mark.asyncio
async def test_store_episode_skips_writing_edges_when_disabled(
    metadata_store: MetadataStore, graph_store: GraphStore
) -> None:
    """enable_graph_recall=False 时不写边 (避免未启用功能用户白付写入成本)。"""
    pipeline = _pipeline(metadata=metadata_store, graph=graph_store, enable_graph_recall=False)
    memory_id = await pipeline.store_episode(
        "聊天气", session_id="s1", user_id="u1", agent_id="a1",
    )
    assert memory_id
    neighbors = await graph_store.neighbors("a1", "user:u1", "mentioned_in")
    assert neighbors == []


@pytest.mark.asyncio
async def test_store_episode_edge_write_failure_does_not_block_store(
    metadata_store: MetadataStore,
) -> None:
    """graph.add_edge 抛异常时 store_episode 仍返回 memory_id (写边失败不影响主链路)。"""

    class _BoomGraph:
        async def add_edge(self, *args, **kwargs):  # noqa: ANN201
            raise RuntimeError("graph add_edge down")

    pipeline = _pipeline(metadata=metadata_store, graph=_BoomGraph(), enable_graph_recall=True)  # type: ignore[arg-type]
    memory_id = await pipeline.store_episode(
        "聊天气", session_id="s1", user_id="u1", agent_id="a1",
    )
    # 主链路 store_episode 仍成功返回 memory_id
    assert memory_id


# ── Reranker provider 注入 (main._build_memory_stack 复用 EXP-3 已验证 provider) ──


def test_reranker_is_available_when_provider_injected() -> None:
    """注入 OpenAICompatRerankerProvider 后 Reranker.is_available()=True。"""
    from isac.memory.reranker import Reranker
    from isac.provider.rerank.openai_compat import OpenAICompatRerankerProvider

    provider = OpenAICompatRerankerProvider("sk-test", "https://rerank.example/v1", "rerank-v1")
    reranker = Reranker({"api_key": "sk", "model": "rerank"}, provider=provider)
    assert reranker.is_available() is True


def test_reranker_unavailable_without_provider() -> None:
    """未注入 provider 时 is_available()=False (零行为变化基线)。"""
    from isac.memory.reranker import Reranker

    reranker = Reranker({})
    assert reranker.is_available() is False


def test_build_memory_stack_injects_reranker_provider_when_configured(tmp_path) -> None:  # noqa: ANN001
    """main._build_memory_stack 给定 reranker.api_key+model 时返回的 Reranker
    is_available()=True; 未配置时保持 False。"""
    from isac.main import _build_memory_stack

    # 启用配置
    memory_config = {
        "reranker": {
            "api_key": "sk-test", "model": "rerank-v1",
            "base_url": "https://rerank.example/v1", "protocol": "cohere",
        },
    }
    # 用 stub 的 tenant_guard/tenant_context 避免 O1 路径
    class _Stub:
        pass
    metadata, _graph, _embed, reranker = _build_memory_stack(memory_config, _Stub(), _Stub())
    assert reranker.is_available() is True

    # 未配置 → False (零行为变化)
    metadata2, _g2, _e2, reranker2 = _build_memory_stack({}, _Stub(), _Stub())
    assert reranker2.is_available() is False
