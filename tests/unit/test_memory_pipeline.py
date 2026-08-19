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
from isac.provider.base import EmbeddingProvider


class _KeywordEmbeddingProvider(EmbeddingProvider):
    """确定性 3 维向量: 按关键词命中生成, 让"语义相近但词面无重叠"可被测试构造。

    含 "天气"/"weather" → [1,0,0]; 含 "美食"/"food" → [0,1,0]; 其余 → [0,0,1]。
    """

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(text) for text in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._vec(query)

    def dimension(self) -> int:
        return 3

    @staticmethod
    def _vec(text: str) -> list[float]:
        lowered = text.lower()
        if "天气" in lowered or "weather" in lowered:
            return [1.0, 0.0, 0.0]
        if "美食" in lowered or "food" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


async def make_pipeline(
    tmp_path, namespace: str = "agent_a", metrics=None, *, embedding_provider=None
) -> MemoryRetrievalPipeline:
    metadata = MetadataStore(str(tmp_path / "memory.db"))
    await metadata.init_schema()
    pipeline = MemoryRetrievalPipeline(
        namespace=namespace,
        metadata=metadata,
        vector=VectorStore(str(tmp_path / "vectors.db"), dimension=3),
        sparse=SparseBM25Index(),
        graph=GraphStore(str(tmp_path / "graph.db")),
        embedder=EmbeddingManager({}, provider=embedding_provider),
        reranker=Reranker({}),
        metrics=metrics,
    )
    _pipelines.append(pipeline)
    return pipeline


# 追踪本模块 make_pipeline 创建的 pipeline, 测试结束统一关闭底层 aiosqlite
# 持久连接 (vector/graph), 避免 "Event loop is closed" / "deleted before being
# closed" 警告 (阶段 0 / 24h soak 前置)。close() 幂等, 与 destroy 路径无冲突。
_pipelines: list[MemoryRetrievalPipeline] = []


@pytest.fixture(autouse=True)
async def _close_pipelines_after_test() -> None:
    yield
    for p in _pipelines:
        await p.vector.close()
        await p.graph.close()
    _pipelines.clear()


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
    await vector.close()  # 关闭持久连接, 避免 aiosqlite 后台线程报错


@pytest.mark.asyncio
async def test_warm_up_sparse_index_restores_from_persistence(tmp_path) -> None:
    """K3: 重启场景—新 SparseBM25Index 从 MetadataStore 加载现有 episodes 重建索引。"""
    pipeline = await make_pipeline(tmp_path, namespace="warm_up")
    await pipeline.store_episode("hello world", "sess-1", "u1")
    await pipeline.store_episode("another doc", "sess-2", "u1")

    # 模拟重启: 创建新 pipeline 但用同一个 metadata.db (共享 SQLite 文件)
    pipeline2 = await make_pipeline(tmp_path, namespace="warm_up")
    # 此时 SparseBM25Index 是空的, 直接 search 应该返回 0
    assert pipeline2.sparse.search("hello") == []

    # 执行预热: 从 SQLite 读取现有 episodes 重建 BM25
    count = await pipeline2.warm_up_sparse_index()
    assert count == 2

    # 预热后 search 能命中
    results = pipeline2.sparse.search("hello")
    assert len(results) == 1
    assert results[0][0]  # memory_id 非空


@pytest.mark.asyncio
async def test_shared_namespace_acl_rejects_without_user_or_group(tmp_path) -> None:
    """K3: shared namespace 检索必须传 user_id 或 group_id, 否则拒绝防跨用户注入。"""
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    pipeline = await make_pipeline(tmp_path, namespace="shared", metrics=metrics)
    await pipeline.store_episode("secret content", "sess-1", "u1")

    # 不传 user_id/group_id 应返回空 + 记录 ACL 拒绝指标
    hits = await pipeline.search("secret", user_id="", group_id="")
    assert hits == []
    assert metrics.counter("isac_memory_acl_rejections_total").value() == 1

    # 传 user_id 后能命中
    hits = await pipeline.search("secret", user_id="u1")
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_tenant_prefixed_shared_namespace_acl_rejects_without_anchor(tmp_path) -> None:
    """2026-08-19 shared ACL 口径统一回归: 租户前缀 shared 命名空间同样强制 ACL。

    此前 pipeline 仅用 `namespace == "shared"` 字面量判断, 租户模式下命名空间为
    `org:tenant:shared` 失配 → 强制 ACL 被绕过, 可无锚点全量检索该租户 shared 空间。
    is_shared_namespace 统一口径后, 前缀形态无 user_id/group_id 也必须被拒。
    """
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    pipeline = await make_pipeline(tmp_path, namespace="org1:tenantA:shared", metrics=metrics)
    await pipeline.store_episode("tenant secret", "sess-1", "u1")

    hits = await pipeline.search("tenant secret", user_id="", group_id="")
    assert hits == []
    assert metrics.counter("isac_memory_acl_rejections_total").value() == 1

    hits = await pipeline.search("tenant secret", user_id="u1")
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_store_episode_failure_records_error_metric(tmp_path) -> None:
    """K3: 写入失败时记 isac_memory_store_errors_total 指标, 不阻塞返回空 ID。"""
    from isac.observability import get_default_metrics

    metrics = get_default_metrics()
    pipeline = await make_pipeline(tmp_path, metrics=metrics)

    # 注入坏的 metadata (close 掉 db 或用坏路径) 触发 store_episode 异常
    pipeline.metadata.db_path = "/nonexistent/path/memory.db"
    result = await pipeline.store_episode("content", "sess-1", "u1")

    assert result == ""
    assert metrics.counter("isac_memory_store_errors_total").value() == 1


@pytest.mark.asyncio
async def test_init_schema_is_idempotent(tmp_path) -> None:
    """K3: 重复调用 init_schema 不报错 (CREATE TABLE IF NOT EXISTS + ALTER TABLE 探测)。"""
    metadata = MetadataStore(str(tmp_path / "memory.db"))
    await metadata.init_schema()
    await metadata.init_schema()  # 第二次不应抛异常
    # 能正常写入
    memory_id = await metadata.store_episode(
        "agent_a",
        {"id": "m1", "content": "hello", "session_id": "s1", "user_id": "u1"},
    )
    assert memory_id == "m1"


# ── CR3-H3: 稠密 (向量) 召回接入 ────────────────────────────────


@pytest.mark.asyncio
async def test_dense_recall_finds_semantic_match_without_keyword_overlap(tmp_path) -> None:
    """CR3-H3: 与 query 无词面重叠的记忆, 通过向量召回也能检索到。"""
    pipeline = await make_pipeline(tmp_path, embedding_provider=_KeywordEmbeddingProvider())

    memory_id = await pipeline.store_episode(
        "今天天气很好", session_id="sess_1", user_id="user_1"
    )
    # query 用英文 weather: 与内容 "今天天气很好" 无任何词面重叠 (FTS/BM25 均不命中),
    # 但 _KeywordEmbeddingProvider 把两者都映射到 [1,0,0] → 向量召回命中。
    hits = await pipeline.search("weather", top_k=3)

    assert [hit.id for hit in hits] == [memory_id]


@pytest.mark.asyncio
async def test_dense_recall_candidates_pass_acl_filter(tmp_path) -> None:
    """CR3-H3: 向量候选必须经 get_episodes_by_ids 的 user/group ACL 过滤。"""
    pipeline = await make_pipeline(tmp_path, embedding_provider=_KeywordEmbeddingProvider())
    id_a = await pipeline.store_episode("今天天气很好", session_id="sess_a", user_id="user_a")
    id_b = await pipeline.store_episode("天气 预报 降雨", session_id="sess_b", user_id="user_b")
    assert id_a and id_b

    # user_a 私聊检索: 向量层两条都命中 [1,0,0], 但 ACL 只放行 user_a 自己的
    hits = await pipeline.search("weather", top_k=10, user_id="user_a")

    assert [hit.id for hit in hits] == [id_a]


@pytest.mark.asyncio
async def test_dense_recall_failure_degrades_to_sparse(tmp_path) -> None:
    """CR3-H3: 稠密路径故障 (embed_query 抛异常) 时降级为纯稀疏检索, 不影响 FTS 命中。"""

    class _BrokenEmbeddingProvider(_KeywordEmbeddingProvider):
        async def embed_query(self, query: str) -> list[float]:
            raise RuntimeError("embedding API down")

    pipeline = await make_pipeline(tmp_path, embedding_provider=_BrokenEmbeddingProvider())
    memory_id = await pipeline.store_episode(
        "ISAC keyword 检索测试", session_id="sess_1", user_id="user_1"
    )

    hits = await pipeline.search("ISAC keyword", top_k=3)

    assert [hit.id for hit in hits] == [memory_id]


@pytest.mark.asyncio
async def test_search_filters_by_topics(tmp_path) -> None:
    """架构债清偿: pipeline.search filters.topics 过滤 (json_each 匹配 episodes.topics)。"""
    pipeline = await make_pipeline(tmp_path, namespace="filter_topics")
    await pipeline.store_episode("项目 记忆 工作", "s1", "u1", metadata={"topics": ["work"]})
    await pipeline.store_episode("项目 记忆 生活", "s2", "u1", metadata={"topics": ["life"]})

    hits_work = await pipeline.search("记忆", top_k=10, user_id="u1", filters={"topics": ["work"]})
    assert hits_work, "topics=work 应命中 work 记忆"
    assert all("工作" in (h.content or "") for h in hits_work)
    assert not any("生活" in (h.content or "") for h in hits_work)

    hits_life = await pipeline.search("记忆", top_k=10, user_id="u1", filters={"topics": ["life"]})
    assert hits_life
    assert all("生活" in (h.content or "") for h in hits_life)


@pytest.mark.asyncio
async def test_search_filters_by_time_range(tmp_path) -> None:
    """架构债清偿: pipeline.search filters.since/until 时间范围过滤 (created_at)。"""
    import aiosqlite

    pipeline = await make_pipeline(tmp_path, namespace="filter_time")
    mid_old = await pipeline.store_episode("旧记忆 时间锚点", "s1", "u1")
    mid_new = await pipeline.store_episode("新记忆 时间锚点", "s2", "u1")
    async with aiosqlite.connect(pipeline.metadata.db_path) as db:
        await db.execute("UPDATE episodes SET created_at = ? WHERE id = ?", (1000, mid_old))
        await db.execute("UPDATE episodes SET created_at = ? WHERE id = ?", (2000, mid_new))
        await db.commit()

    hits_since = await pipeline.search("时间", top_k=10, user_id="u1", filters={"since": 1500})
    ids_since = {h.id for h in hits_since}
    assert mid_new in ids_since and mid_old not in ids_since, "since=1500 应只命中 created_at>=1500"

    hits_until = await pipeline.search("时间", top_k=10, user_id="u1", filters={"until": 1500})
    ids_until = {h.id for h in hits_until}
    assert mid_old in ids_until and mid_new not in ids_until, "until=1500 应只命中 created_at<=1500"


@pytest.mark.asyncio
async def test_store_episode_returns_id_on_vector_dim_mismatch(tmp_path) -> None:
    """N5b 批次E 项3: vector.upsert 维度错配抛错时 episode 仍入库, 返回真实 memory_id。

    修复前: vector.upsert 抛 ValueError 被外层 except 吞, 返回 "" → 幽灵条目 + 调用方误判。
    """

    class _WrongDimEmbedder:
        """维度错配的 embedding provider (返回 4 维, vector store dimension=3)。"""

        async def embed(self, texts):  # noqa: ANN001
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

        async def embed_query(self, query):  # noqa: ANN001
            return [1.0, 0.0, 0.0, 0.0]

        def dimension(self) -> int:
            return 4

        def is_degraded(self) -> bool:
            return False

    pipeline = await make_pipeline(tmp_path, namespace="dim_mismatch", embedding_provider=_WrongDimEmbedder())
    mid = await pipeline.store_episode("内容 关键词", "sess-1", "u1")
    assert mid, "vector 维度错配时 episode 应仍入库并返回真实 memory_id (不返回空串)"
    # episode 确实落盘 (FTS 可查到)
    rows = await pipeline.metadata.search_fts("dim_mismatch", "关键词")
    assert any(r.get("id") == mid for r in rows), "错配的 episode 应已在 SQLite 持久化"
